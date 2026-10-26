"""HullSurgeYawModel: the generated hull's design points hold in the horizontal-plane model."""

import math

import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import scaled_vessel
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel, damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics

AT_REST = HullState(x=0.0, y=0.0, heading=0.0, surge=0.0, sway=0.0, yaw_rate=0.0)


@pytest.fixture(params=["5m", "30m"])
def hull(request):
    vessel = scaled_vessel(request.param)
    dynamics = derive_vessel_dynamics(vessel, 0.0, {})
    return dynamics, HullSurgeYawModel(dynamics)


def run(model, state, port, starboard, seconds, dt=0.01):
    for _ in range(int(round(seconds / dt))):
        state = model.step(state, port, starboard, dt)
    return state


def test_damping_opposes_the_velocity_both_ways():
    assert damping(-2.0, -3.0, 2.0) == pytest.approx(16.0)
    assert damping(-2.0, -3.0, -2.0) == pytest.approx(-16.0)


def test_full_thrust_settles_at_the_design_speed(hull):
    dynamics, model = hull
    state = run(model, AT_REST, dynamics.max_thrust, dynamics.max_thrust, 600.0)
    assert state.surge == pytest.approx(dynamics.design_speed, rel=1e-3)
    assert state.heading == 0.0 and state.y == 0.0


def test_full_differential_thrust_settles_at_the_design_yaw_rate(hull):
    dynamics, model = hull
    state = run(model, AT_REST, -dynamics.max_thrust, dynamics.max_thrust, 200.0)
    assert state.yaw_rate == pytest.approx(dynamics.design_yaw_rate, rel=1e-3)


def test_the_starboard_thruster_turns_the_hull_to_port(hull):
    """Port is +y, so more thrust to starboard turns counterclockwise, as headings count."""
    dynamics, model = hull
    state = run(model, AT_REST, 0.0, dynamics.max_thrust, 5.0)
    assert state.yaw_rate > 0 and state.heading > 0


def test_thrust_is_limited_to_the_thruster_maximum(hull):
    dynamics, model = hull
    capped = run(model, AT_REST, 10 * dynamics.max_thrust, 10 * dynamics.max_thrust, 1.0)
    full = run(model, AT_REST, dynamics.max_thrust, dynamics.max_thrust, 1.0)
    assert capped == full


def test_the_pose_follows_the_heading(hull):
    dynamics, model = hull
    north = HullState(x=0.0, y=0.0, heading=math.pi / 2, surge=1.0, sway=0.0, yaw_rate=0.0)
    state = model.step(north, 0.0, 0.0, 0.1)
    assert state.x == pytest.approx(0.0, abs=1e-12)
    assert state.y > 0
