"""TwinThrustAutopilot: gains from the hull model, closed-loop heading and speed on it, thrust limits and anti-windup."""

import dataclasses
import math

import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import VESSEL_SCALES, scaled_vessel
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import DISCRETE_LIMIT, AutopilotGains, HullObservation, TwinThrustAutopilot
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics

CONTROL_DT = 0.1


def setup(scale):
    vessel = scaled_vessel(scale)
    dynamics = derive_vessel_dynamics(vessel, 0.0, {})
    gains = AutopilotGains.from_dynamics(dynamics, vessel, CONTROL_DT)
    return vessel, dynamics, TwinThrustAutopilot(gains), HullSurgeYawModel(dynamics)


def fly(autopilot, model, state, heading, speed, seconds, record=None):
    for _ in range(int(round(seconds / CONTROL_DT))):
        command = autopilot.command(heading, speed, HullObservation(state.heading, state.surge, state.yaw_rate), CONTROL_DT)
        if record is not None:
            record.append(command)
        for _ in range(20):
            state = model.step(state, command.port, command.starboard, CONTROL_DT / 20)
    return state


class TestGains:
    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_gains_are_positive(self, scale):
        gains = setup(scale)[2].gains
        for name in ("speed_p", "speed_i", "rate_p", "rate_i", "heading_p", "heading_deceleration"):
            assert getattr(gains, name) > 0, name

    def test_the_loop_frequency_respects_the_control_step(self):
        vessel = scaled_vessel("30m")
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        coarse = AutopilotGains.from_dynamics(dynamics, vessel, 1.0)
        fine = AutopilotGains.from_dynamics(dynamics, vessel, 0.01)
        assert coarse.heading_p < fine.heading_p
        assert coarse.rate_i / coarse.yaw_inertia == pytest.approx(DISCRETE_LIMIT**2, rel=1e-9)

    def test_the_turn_rate_demand_is_continuous_and_limited(self):
        autopilot = setup("5m")[2]
        demands = [autopilot.turn_rate_demand(math.radians(error)) for error in range(-180, 181)]
        assert max(abs(demand) for demand in demands) <= autopilot.gains.max_turn_rate
        assert all(abs(a - b) < 0.05 for a, b in zip(demands, demands[1:]))
        assert autopilot.turn_rate_demand(0.0) == 0.0
        assert autopilot.turn_rate_demand(0.3) == -autopilot.turn_rate_demand(-0.3)


class TestClosedLoop:
    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_it_reaches_the_commanded_speed_and_holds_the_heading(self, scale):
        vessel, _, autopilot, model = setup(scale)
        cruise = VESSEL_SCALES[scale].cruise_speed
        state = fly(autopilot, model, HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, cruise, 2 * cruise / vessel.max_acceleration + 120.0)
        assert state.surge == pytest.approx(cruise, rel=1e-3)
        assert abs(state.heading) < 1e-6
        assert abs(state.y) < 1e-6

    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_a_quarter_turn_completes_without_overshoot(self, scale):
        vessel, _, autopilot, model = setup(scale)
        cruise = VESSEL_SCALES[scale].cruise_speed
        autopilot.reset(cruise)
        state = HullState(0.0, 0.0, 0.0, cruise, 0.0, 0.0)
        quarter_turn_s = (math.pi / 2) / vessel.max_angular_speed
        headings = []
        for _ in range(int(round((4 * quarter_turn_s + 60.0) / CONTROL_DT))):
            state = fly(autopilot, model, state, math.pi / 2, cruise, CONTROL_DT)
            headings.append(state.heading)
        assert max(headings) < math.pi / 2 + math.radians(0.5), "no overshoot beyond half a degree"
        assert headings[-1] == pytest.approx(math.pi / 2, abs=math.radians(0.05))
        assert abs(state.yaw_rate) < 1e-3

    def test_the_speed_reference_ramps_at_the_vessels_max_acceleration(self):
        vessel, _, autopilot, model = setup("30m")
        state = HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        fly(autopilot, model, state, 0.0, 8.0, 5.0)
        assert autopilot._speed_reference == pytest.approx(5.0 * vessel.max_acceleration)


class TestLimits:
    def test_thrust_stays_within_the_thruster_limits(self):
        _, dynamics, autopilot, model = setup("5m")
        commands = []
        fly(autopilot, model, HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), math.pi, 4.0, 30.0, commands)
        for command in commands:
            assert abs(command.port) <= dynamics.max_thrust + 1e-9
            assert abs(command.starboard) <= dynamics.max_thrust + 1e-9
        assert any(command.yaw_saturated for command in commands), "a half turn from rest saturates the yaw"

    def test_yaw_has_priority_over_surge(self):
        autopilot = setup("5m")[2]
        command = autopilot.command(math.pi / 2, 4.0, HullObservation(0.0, 0.0, 0.0), CONTROL_DT)
        assert command.yaw_saturated
        assert command.port == pytest.approx(-command.starboard), "the whole thrust goes to the differential"

    def test_integrators_hold_while_their_loop_saturates(self):
        """Anti-windup: an unreachable speed does not wind the speed integral up."""
        _, dynamics, autopilot, model = setup("5m")
        state = HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        autopilot.gains = dataclasses.replace(autopilot.gains, max_speed=100.0, max_acceleration=100.0)
        fly(autopilot, model, state, 0.0, 100.0, 60.0)
        held = autopilot._speed_integral
        fly(autopilot, model, state, 0.0, 100.0, 60.0)
        assert autopilot._speed_integral == pytest.approx(held, abs=1e-6)


def test_reset_clears_the_integrators_and_restarts_the_speed_reference():
    _, _, autopilot, model = setup("5m")
    fly(autopilot, model, HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 1.0, 3.0, 20.0)
    autopilot.reset(2.0)
    assert autopilot._rate_integral == 0.0 and autopilot._speed_integral == 0.0
    assert autopilot._speed_reference == 2.0
