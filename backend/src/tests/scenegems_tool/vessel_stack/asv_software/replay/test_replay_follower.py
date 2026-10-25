"""ReplayFollower: reference interpolation, tracking on the reference and pure pursuit when off it."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

VESSEL = make_vessel(0, True, length=30.0)


def reference_line(count: int = 100, speed: float = 5.0):
    """Straight east at `speed`, one state per second."""
    return [ActorState(x=speed * t, y=0.0, speed=speed, heading=0.0) for t in range(count)]


def observation(state: ActorState, time: float = 0.0) -> VesselStateObservation:
    return VesselStateObservation(sim_time=time, vessel=VESSEL, own_state=state, target_states={})


def request(time: float, dt: float = 1.0, index: int = 0) -> StepRequest:
    return StepRequest(index=index, time=time, target_time=time + dt)


class TestConstruction:
    def test_empty_reference_is_rejected(self):
        with pytest.raises(ValueError, match="empty reference trajectory"):
            ReplayFollower(VESSEL, [], 1.0)

    @pytest.mark.parametrize("time_step", [0, -1.0])
    def test_non_positive_reference_time_step_is_rejected(self, time_step):
        with pytest.raises(ValueError, match="reference_time_step must be positive"):
            ReplayFollower(VESSEL, reference_line(), time_step)

    def test_participant_id_names_the_vessel(self):
        assert ReplayFollower(VESSEL, reference_line(), 1.0).participant_id == "replay/0"

    def test_default_tolerance_is_a_tenth_of_the_length_but_at_least_one_meter(self):
        assert ReplayFollower(make_vessel(0, True, length=30.0), reference_line(), 1.0).position_tolerance_m == 3.0
        assert ReplayFollower(make_vessel(0, True, length=5.0), reference_line(), 1.0).position_tolerance_m == 1.0

    def test_tolerance_can_be_set(self):
        assert ReplayFollower(VESSEL, reference_line(), 1.0, position_tolerance_m=7.0).position_tolerance_m == 7.0

    def test_start_accepts_a_seed(self):
        ReplayFollower(VESSEL, reference_line(), 1.0).start(123)


class TestReferenceState:
    def test_samples_are_returned_exactly(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0)
        state = follower.reference_state(10.0)
        assert (state.x, state.speed) == (50.0, 5.0)

    def test_interpolates_between_samples(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0)
        assert follower.reference_state(10.25).x == pytest.approx(51.25)

    def test_respects_the_reference_time_step(self):
        follower = ReplayFollower(VESSEL, [ActorState(0.0, 0.0, 1.0, 0.0), ActorState(10.0, 0.0, 1.0, 0.0)], 4.0)
        assert follower.reference_state(2.0).x == pytest.approx(5.0)

    def test_holds_the_first_state_before_the_start(self):
        assert ReplayFollower(VESSEL, reference_line(), 1.0).reference_state(-5.0).x == 0.0

    def test_holds_the_last_state_after_the_end(self):
        follower = ReplayFollower(VESSEL, reference_line(count=10), 1.0)
        assert follower.reference_state(500.0).x == 45.0

    def test_heading_interpolates_along_the_shortest_arc(self):
        states = [ActorState(0.0, 0.0, 1.0, math.radians(170)), ActorState(1.0, 0.0, 1.0, math.radians(-170))]
        heading = ReplayFollower(VESSEL, states, 1.0).reference_state(0.5).heading
        assert abs(abs(heading) - math.pi) < 1e-9


class TestOnStep:
    def test_on_the_reference_it_commands_the_reference_at_the_target_time(self):
        reference = [ActorState(x=float(t), y=0.0, speed=1.0 + t, heading=0.1 * t) for t in range(10)]
        follower = ReplayFollower(VESSEL, reference, 1.0)
        command = follower.on_step(request(time=3.0), observation(reference[3], 3.0))
        assert command.heading == pytest.approx(0.4)
        assert command.speed == pytest.approx(5.0)

    def test_within_the_tolerance_counts_as_on_the_reference(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, position_tolerance_m=3.0)
        command = follower.on_step(request(time=10.0), observation(ActorState(50.0, 2.9, 5.0, 0.0), 10.0))
        assert command.heading == 0.0
        assert command.speed == 5.0

    def test_off_the_reference_it_steers_at_the_point_ten_seconds_ahead(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, position_tolerance_m=3.0)
        own = ActorState(50.0, -40.0, 5.0, 0.0)
        command = follower.on_step(request(time=10.0), observation(own, 10.0))
        carrot = follower.reference_state(20.0)
        assert command.heading == pytest.approx(math.atan2(carrot.y - own.y, carrot.x - own.x))
        assert command.heading > 0.0, "the reference is north of the vessel, so the heading turns toward north"
        gap = math.hypot(carrot.x - own.x, carrot.y - own.y)
        assert command.speed == pytest.approx(min(gap / 10.0, VESSEL.max_speed))

    def test_pursuit_speed_is_limited_to_the_vessel_maximum(self):
        slow_vessel = make_vessel(0, True, max_speed=6.0)
        follower = ReplayFollower(slow_vessel, reference_line(), 1.0, position_tolerance_m=3.0)
        command = follower.on_step(request(time=10.0), observation(ActorState(-500.0, 0.0, 5.0, 0.0), 10.0))
        assert command.speed == 6.0

    def test_lookahead_is_configurable(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, lookahead_s=2.0, position_tolerance_m=3.0)
        command = follower.on_step(request(time=10.0), observation(ActorState(50.0, -40.0, 5.0, 0.0), 10.0))
        carrot = follower.reference_state(12.0)
        assert command.heading == pytest.approx(math.atan2(-(-40.0), carrot.x - 50.0))

    def test_exactly_at_the_carrot_it_takes_the_carrot_heading_and_speed(self):
        # A vessel at the held end of the reference is off it by more than the tolerance only if it
        # is displaced; a zero gap to the carrot happens when the reference stands still ahead of it.
        reference = [ActorState(0.0, 0.0, 0.0, 1.0), ActorState(0.0, 0.0, 0.0, 1.0)]
        follower = ReplayFollower(VESSEL, reference, 1.0, position_tolerance_m=-1.0)
        command = follower.on_step(request(time=0.0), observation(ActorState(0.0, 0.0, 0.0, 0.0)))
        assert (command.heading, command.speed) == (1.0, 0.0)

    def test_a_follower_is_a_pure_function_of_time_and_observation(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, position_tolerance_m=3.0)
        own = ActorState(50.0, -40.0, 5.0, 0.0)
        first = follower.on_step(request(time=10.0), observation(own, 10.0))
        second = follower.on_step(request(time=10.0), observation(own, 10.0))
        assert first == second
