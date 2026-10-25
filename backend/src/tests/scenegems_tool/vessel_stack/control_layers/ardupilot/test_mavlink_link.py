"""MavlinkLink against a fake SITL connection: message handling, readiness, engagement and commands."""

import math

import pytest
from pymavlink import mavutil

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import (
    EKF_READY_TEXT,
    GUIDED_TARGET_TIMEOUT_S,
    ROVER_GUIDED_MODE,
    ROVER_HOLD_MODE,
    MavlinkLink,
    MavlinkLinkError,
    StampedState,
    sitl_mavlink_endpoint,
)
from tests.scenegems_tool.vessel_stack.control_layers.ardupilot.fake_sitl import FakeSitlConnection, attach, message
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE


@pytest.fixture
def link():
    link = MavlinkLink("tcp:vessel_0:5760", 0, GEOFENCE)
    yield link
    link.close()


@pytest.fixture
def connected(link):
    connection = attach(link, FakeSitlConnection(GEOFENCE))
    return link, connection


def position_message(boot_ms, x=0.0, y=0.0, vx_cm=0, vy_cm=0, hdg_cdeg=9000, system=1):
    latitude, longitude = GEOFENCE.to_lat_long((x, y))
    return message("GLOBAL_POSITION_INT", system=system, time_boot_ms=boot_ms, lat=int(round(latitude * 1e7)), lon=int(round(longitude * 1e7)), vx=vx_cm, vy=vy_cm, hdg=hdg_cdeg)


def stamped(boot_ms, x, y=0.0, speed=1.0, heading=0.0):
    return StampedState(boot_ms=boot_ms, state=ActorState(x=x, y=y, speed=speed, heading=heading))


class TestEndpoint:
    @pytest.mark.parametrize("vessel_id,port", [(0, 5760), (1, 5770), (3, 5790)])
    def test_sitl_serial0_port_is_5760_plus_10_per_vessel(self, vessel_id, port):
        assert sitl_mavlink_endpoint("vessel_x", vessel_id) == f"tcp:vessel_x:{port}"

    def test_participant_id_names_the_vessel(self, link):
        assert link.participant_id == "mavlink/0"

    def test_not_connected_raises(self, link):
        with pytest.raises(MavlinkLinkError, match="not connected"):
            link.drain()
        with pytest.raises(MavlinkLinkError, match="not connected"):
            link.send_heading_speed(HeadingSpeedCommand(0.0, 1.0))


class TestHandle:
    def test_position_message_becomes_a_local_state(self, connected):
        link, _ = connected
        link._handle(position_message(1000, x=120.0, y=-40.0, vx_cm=0, vy_cm=500, hdg_cdeg=9000))
        (sample,) = link.samples
        assert sample.boot_ms == 1000
        assert sample.state.x == pytest.approx(120.0, abs=0.01)
        assert sample.state.y == pytest.approx(-40.0, abs=0.01)
        assert sample.state.speed == pytest.approx(5.0)
        assert sample.state.heading == pytest.approx(0.0, abs=1e-9), "true north 90 degrees is east, heading 0"

    @pytest.mark.parametrize("hdg_cdeg,heading", [(0, math.pi / 2), (18000, -math.pi / 2), (27000, math.pi)])
    def test_reported_heading_is_converted_from_true_north(self, connected, hdg_cdeg, heading):
        link, _ = connected
        link._handle(position_message(1000, hdg_cdeg=hdg_cdeg))
        assert abs(math.remainder(link.samples[0].state.heading - heading, 2 * math.pi)) < 1e-9

    def test_unknown_heading_falls_back_to_the_velocity_direction(self, connected):
        link, _ = connected
        link._handle(position_message(1000, vx_cm=0, vy_cm=300, hdg_cdeg=65535))
        assert link.samples[0].state.heading == pytest.approx(0.0, abs=1e-9)
        link._handle(position_message(1040, vx_cm=300, vy_cm=0, hdg_cdeg=65535))
        assert link.samples[1].state.heading == pytest.approx(math.pi / 2)

    def test_boot_time_only_moves_forward(self, connected):
        link, _ = connected
        link._handle(position_message(2000))
        link._handle(position_message(1500))
        assert link.boot_ms == 2000

    def test_messages_from_other_systems_are_ignored(self, connected):
        link, _ = connected
        link._handle(position_message(1000, system=2))
        assert link.samples == []
        assert link.boot_ms is None

    def test_bad_data_is_ignored(self, connected):
        link, _ = connected
        link._handle(message("BAD_DATA"))
        assert link.samples == []

    def test_ekf_text_makes_the_link_ready(self, connected):
        link, _ = connected
        assert not link._ekf_ready
        link._handle(message("STATUSTEXT", text=EKF_READY_TEXT))
        assert link._ekf_ready
        assert link.status_texts == [(None, EKF_READY_TEXT)]

    def test_heartbeats_before_the_ekf_is_ready_do_not_count(self, connected):
        link, _ = connected
        link._handle(message("HEARTBEAT", base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED, custom_mode=ROVER_GUIDED_MODE))
        assert not link.in_guided

    def test_heartbeat_after_ready_reports_armed_and_mode(self, connected):
        link, _ = connected
        link._handle(message("STATUSTEXT", text=EKF_READY_TEXT))
        link._handle(message("HEARTBEAT", base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED, custom_mode=ROVER_GUIDED_MODE))
        assert link.in_guided

    def test_heartbeat_of_another_component_is_ignored(self, connected):
        link, _ = connected
        link._handle(message("STATUSTEXT", text=EKF_READY_TEXT))
        link._handle(message("HEARTBEAT", component=191, base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED, custom_mode=ROVER_GUIDED_MODE))
        assert not link.in_guided


class TestStateAt:
    def test_none_until_a_sample_at_or_after_the_boundary_arrived(self, link):
        link.samples = [stamped(1000, 0.0)]
        assert link.state_at(1040) is None

    def test_exact_sample_is_returned_as_is(self, link):
        link.samples = [stamped(1000, 0.0), stamped(1040, 1.0)]
        sample = link.state_at(1040)
        assert (sample.boot_ms, sample.state.x) == (1040, 1.0)

    def test_between_samples_the_state_is_interpolated_to_the_boundary(self, link):
        link.samples = [stamped(1000, 0.0, speed=1.0), stamped(1040, 4.0, speed=3.0)]
        sample = link.state_at(1010)
        assert sample.boot_ms == 1010
        assert sample.state.x == pytest.approx(1.0)
        assert sample.state.speed == pytest.approx(1.5)

    def test_heading_interpolates_the_short_way_round(self, link):
        link.samples = [stamped(1000, 0.0, heading=math.radians(170)), stamped(1040, 1.0, heading=math.radians(-170))]
        assert abs(abs(link.state_at(1020).state.heading) - math.pi) < 1e-9

    def test_a_boundary_before_the_first_sample_takes_the_first_sample(self, link):
        link.samples = [stamped(1000, 7.0)]
        sample = link.state_at(900)
        assert (sample.boot_ms, sample.state.x) == (900, 7.0)

    def test_first_sample_at_skips_earlier_samples_for_later_calls(self, link):
        link.samples = [stamped(1000, 0.0), stamped(1040, 1.0), stamped(1080, 2.0)]
        assert link.first_sample_at(1050).boot_ms == 1080
        assert link._cursor == 2
        assert link.first_sample_at(1090) is None

    def test_which_sample_is_chosen_depends_only_on_sitl_time(self, link):
        link.samples = [stamped(1000, 0.0), stamped(1040, 4.0)]
        first = link.state_at(1020)
        link.samples.append(stamped(1080, 8.0))
        assert link.state_at(1020).state.x == first.state.x


class TestEngagement:
    def test_engagement_requires_a_ready_ekf(self, connected):
        link, _ = connected
        with pytest.raises(MavlinkLinkError, match="engagement before the EKF is ready"):
            link.begin_engagement()

    def test_wait_until_ready_times_out_with_the_last_texts(self, connected):
        link, _ = connected
        link.status_texts.append((1, "PreArm: waiting"))
        with pytest.raises(MavlinkLinkError, match="not seen within -1 s"):
            link.wait_until_ready(timeout_s=-1.0)

    def test_wait_until_ready_polls_until_the_ekf_reports(self, connected):
        link, connection = connected
        link.wait_until_ready(timeout_s=10.0)
        assert link._ekf_ready
        assert connection.time_ms >= connection.ekf_at_ms
        assert len(connection.mav.named("command_long_send")) == 2, "the stream request is repeated after boot"

    def test_engage_switches_to_hold_then_arms(self, connected):
        link, connection = connected
        link.wait_until_ready(timeout_s=10.0)
        boot_ms = link.engage(timeout_s=60.0)
        assert connection.mode == ROVER_HOLD_MODE
        assert connection.armed
        assert boot_ms > connection.ekf_at_ms
        sent = [call for call, _ in connection.mav.calls]
        assert sent.index("set_mode_send") < max(index for index, call in enumerate(sent) if call == "command_long_send")

    def test_engagement_attempts_are_two_seconds_of_sitl_time_apart(self, connected):
        link, connection = connected
        link._handle(message("STATUSTEXT", text=EKF_READY_TEXT))
        link.begin_engagement()
        link._boot_ms = 10_000
        assert not link.advance_engagement()
        link._boot_ms = 11_000
        assert not link.advance_engagement()
        link._boot_ms = 12_000
        assert not link.advance_engagement()
        assert len(connection.mav.named("set_mode_send")) == 2

    def test_engage_times_out_when_the_vessel_never_arms(self, connected):
        link, connection = connected
        connection.on_send = lambda name, args: None  # the vessel ignores every command
        link._handle(message("STATUSTEXT", text=EKF_READY_TEXT))
        with pytest.raises(MavlinkLinkError, match="not armed in HOLD"):
            link.engage(timeout_s=-1.0)


class TestCommands:
    def test_first_command_switches_to_guided_once(self, connected):
        link, connection = connected
        link.send_heading_speed(HeadingSpeedCommand(0.0, 3.0), 1000)
        link.send_heading_speed(HeadingSpeedCommand(0.0, 3.0), 2000)
        modes = connection.mav.named("set_mode_send")
        assert len(modes) == 1
        assert modes[0][2] == ROVER_GUIDED_MODE

    @pytest.mark.parametrize("heading,yaw", [(0.0, math.pi / 2), (math.pi / 2, 0.0), (math.pi, -math.pi / 2), (-math.pi / 2, math.pi)])
    def test_heading_is_sent_as_a_true_north_yaw(self, connected, heading, yaw):
        link, connection = connected
        link.send_heading_speed(HeadingSpeedCommand(heading, 3.0), 1000)
        sent_yaw = connection.mav.named("set_position_target_local_ned_send")[0][14]
        assert abs(math.remainder(sent_yaw - yaw, 2 * math.pi)) < 1e-9

    def test_speed_goes_into_vx_and_negative_speed_is_clamped(self, connected):
        link, connection = connected
        link.send_heading_speed(HeadingSpeedCommand(0.0, 3.5), 1000)
        link.send_heading_speed(HeadingSpeedCommand(0.0, -2.0), 2000)
        first, second = connection.mav.named("set_position_target_local_ned_send")
        assert first[8] == 3.5 and first[9] == 0
        assert second[8] == 0.0

    def test_target_carries_the_simulated_time_and_the_heading_speed_mask(self, connected):
        from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import HEADING_SPEED_TYPE_MASK

        link, connection = connected
        link.send_heading_speed(HeadingSpeedCommand(0.0, 3.0), (1 << 32) + 1234)
        args = connection.mav.named("set_position_target_local_ned_send")[0]
        assert args[0] == 1234, "the time is the low 32 bits, as MAVLink time_boot_ms"
        assert args[4] == HEADING_SPEED_TYPE_MASK
        assert args[3] == mavutil.mavlink.MAV_FRAME_LOCAL_NED

    def test_position_target_is_sent_in_global_coordinates(self, connected):
        link, connection = connected
        link.send_position_target((300.0, 100.0), 5000)
        args = connection.mav.named("set_position_target_global_int_send")[0]
        latitude, longitude = args[5] / 1e7, args[6] / 1e7
        x, y = GEOFENCE.to_coord(latitude, longitude)
        assert (x, y) == pytest.approx((300.0, 100.0), abs=0.05)
        assert len(connection.mav.named("set_mode_send")) == 1

    def test_guided_timeout_constant_matches_rover(self):
        assert GUIDED_TARGET_TIMEOUT_S == 3.0


class TestPolling:
    def test_poll_handles_what_arrives_and_drain_the_rest(self, connected):
        link, connection = connected
        assert link.poll(1.0)
        assert link.samples, "one read cycle delivers a burst of position samples"
        assert connection.time_ms > 10_000

    def test_boot_time_follows_the_stream(self, connected):
        link, connection = connected
        link.poll(1.0)
        assert link.boot_ms == connection.time_ms

    def test_context_manager_closes_the_connection(self):
        link = MavlinkLink("tcp:vessel_0:5760", 0, GEOFENCE)
        connection = attach(link, FakeSitlConnection(GEOFENCE))
        with link:
            pass
        assert connection.closed
        with pytest.raises(MavlinkLinkError):
            link.drain()
