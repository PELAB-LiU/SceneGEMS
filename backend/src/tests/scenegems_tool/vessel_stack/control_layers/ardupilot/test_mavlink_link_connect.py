"""MavlinkLink.connect: the retry loop around pymavlink's connection and the handshake after the first heartbeat."""

from types import SimpleNamespace

import pytest
from pymavlink import mavutil

from scenegems_tool.vessel_stack.control_layers.ardupilot import mavlink_link
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import MavlinkLink, MavlinkLinkError
from tests.scenegems_tool.vessel_stack.control_layers.ardupilot.fake_sitl import SentMessages
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE

ENDPOINT = "tcp:vessel_0:5760"


class FakeClock:
    """Time that only moves when connect sleeps, so the retry loop needs no real waiting."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeConnection:
    target_system = 1
    target_component = 0

    def __init__(self, heartbeat_component=1, heartbeat=True):
        self.mav = SentMessages(self)
        self.heartbeat_component = heartbeat_component
        self.heartbeat = heartbeat
        self.heartbeat_timeouts = []
        self.closed = False

    def on_send(self, name, args):
        pass

    def wait_heartbeat(self, timeout):
        self.heartbeat_timeouts.append(timeout)
        return SimpleNamespace(get_srcComponent=lambda: self.heartbeat_component) if self.heartbeat else None

    def close(self):
        self.closed = True


@pytest.fixture
def clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(mavlink_link.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mavlink_link.time, "sleep", clock.sleep)
    return clock


def serve(monkeypatch, *outcomes):
    """Make mavlink_connection return or raise the given outcomes in order; the last one repeats."""
    attempts = []

    def mavlink_connection(endpoint, **options):
        attempts.append((endpoint, options))
        outcome = outcomes[min(len(attempts), len(outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(mavutil, "mavlink_connection", mavlink_connection)
    return attempts


def test_connect_addresses_the_autopilot_and_starts_the_handshake(monkeypatch, clock):
    connection = FakeConnection(heartbeat_component=7)
    attempts = serve(monkeypatch, connection)
    link = MavlinkLink(ENDPOINT, 0, GEOFENCE, stream_interval_s=0.04, source_system=250)
    link.connect()
    assert attempts == [(ENDPOINT, {"source_system": 250, "autoreconnect": False})]
    assert connection.target_component == 7  # the heartbeat's component, not broadcast
    heartbeats = connection.mav.named("heartbeat_send")
    assert heartbeats == [(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)]
    streams = connection.mav.named("command_long_send")
    assert [(args[0], args[1], args[2], args[4], args[5]) for args in streams] == [
        (1, 7, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, pytest.approx(40_000.0)),
        (1, 7, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, mavutil.mavlink.MAVLINK_MSG_ID_SYSTEM_TIME, pytest.approx(1_000_000.0)),
    ]
    assert clock.sleeps == []
    assert not connection.closed
    link.close()
    assert connection.closed


def test_connection_errors_are_retried_every_second_until_sitl_is_up(monkeypatch, clock):
    connection = FakeConnection()
    attempts = serve(monkeypatch, ConnectionRefusedError("down"), OSError("still starting"), connection)
    link = MavlinkLink(ENDPOINT, 0, GEOFENCE)
    link.connect()
    assert len(attempts) == 3 and clock.sleeps == [1.0, 1.0]
    link.close()


def test_a_connection_without_a_heartbeat_is_closed_and_tried_again(monkeypatch, clock):
    silent, alive = FakeConnection(heartbeat=False), FakeConnection()
    serve(monkeypatch, silent, alive)
    link = MavlinkLink(ENDPOINT, 0, GEOFENCE)
    link.connect()
    assert silent.closed and not alive.closed
    assert silent.heartbeat_timeouts == [5.0]  # at most five seconds per attempt
    link.close()


def test_the_heartbeat_wait_never_outlasts_the_remaining_time(monkeypatch, clock):
    silent = FakeConnection(heartbeat=False)
    serve(monkeypatch, silent)
    with pytest.raises(MavlinkLinkError):
        MavlinkLink(ENDPOINT, 0, GEOFENCE).connect(timeout_s=3.0)
    assert silent.heartbeat_timeouts[0] == pytest.approx(3.0)
    assert all(timeout <= 3.0 for timeout in silent.heartbeat_timeouts)


def test_connect_gives_up_with_the_last_error_after_the_timeout(monkeypatch, clock):
    attempts = serve(monkeypatch, OSError("no route to host"))
    link = MavlinkLink(ENDPOINT, 0, GEOFENCE)
    with pytest.raises(MavlinkLinkError, match=r"tcp:vessel_0:5760: no heartbeat within 3 s \(last error: no route to host\)"):
        link.connect(timeout_s=3.0)
    assert len(attempts) == 3 and clock.sleeps == [1.0, 1.0, 1.0]
    with pytest.raises(MavlinkLinkError, match="not connected"):
        link.drain()


def test_other_errors_are_not_swallowed(monkeypatch, clock):
    serve(monkeypatch, RuntimeError("bad endpoint"))
    with pytest.raises(RuntimeError, match="bad endpoint"):
        MavlinkLink(ENDPOINT, 0, GEOFENCE).connect()
