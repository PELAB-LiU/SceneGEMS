"""UsvNavigationParameters.from_reference: how SceneGEMS derives the runtime configuration from a scenario."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import (
    DEFAULT_CONTROL_HORIZON_STEPS,
    DEFAULT_PRESCRIBED_TIME_S,
    UsvNavigationParameters,
)
from tests.scenegems_tool.vessel_stack.scenarios import SPEED, encounter_trajectories, make_vessel


@pytest.fixture
def head_on():
    trajectories = encounter_trajectories("head_on", 100)
    own = trajectories.initial_scene.os
    return trajectories, own


def test_goal_is_the_end_of_the_generated_trajectory(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.goal == (pytest.approx(100 * SPEED), 0.0)


def test_speed_is_the_initial_reference_speed(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.speed == SPEED


def test_speed_is_capped_at_the_vessel_maximum():
    own = make_vessel(0, True, max_speed=5.0)
    states = [ActorState(0.0, 0.0, 9.0, 0.0), ActorState(9.0, 0.0, 9.0, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.speed == 5.0


def test_speed_falls_back_to_the_mean_when_the_vessel_starts_at_rest():
    own = make_vessel(0, True)
    states = [ActorState(0.0, 0.0, 0.0, 0.0), ActorState(4.0, 0.0, 4.0, 0.0), ActorState(8.0, 0.0, 8.0, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.speed == pytest.approx(4.0)


def test_a_vessel_that_never_moves_is_rejected():
    own = make_vessel(0, True)
    with pytest.raises(ValueError, match="no positive reference speed"):
        UsvNavigationParameters.from_reference(own, [ActorState(0.0, 0.0, 0.0, 0.0)], [own], 1.0)


def test_an_empty_reference_is_rejected():
    own = make_vessel(0, True)
    with pytest.raises(ValueError, match="empty reference trajectory"):
        UsvNavigationParameters.from_reference(own, [], [own], 1.0)


def test_safety_radius_is_the_largest_in_the_scene():
    own = make_vessel(0, True, length=30.0)
    large = make_vessel(1, False, length=100.0)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own, large], 1.0)
    assert parameters.safety_radius == large.safety_radius == 400.0


def test_control_horizon_is_the_sixty_steps_when_the_vessel_turns_fast():
    own = make_vessel(0, True, max_angular_speed=1.0)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 2.0)
    assert parameters.control_horizon == DEFAULT_CONTROL_HORIZON_STEPS * 2.0


def test_control_horizon_covers_a_full_turn_of_a_slow_turning_vessel():
    own = make_vessel(0, True, max_angular_speed=0.05)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.control_horizon == pytest.approx(2 * math.pi / 0.05)


def test_prescribed_time_is_the_upstream_default(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.prescribed_time == DEFAULT_PRESCRIBED_TIME_S == 3.0


def test_runtime_kwargs_and_as_dict(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    kwargs = parameters.runtime_kwargs()
    assert set(kwargs) == {"Cs", "v", "tp", "tp_control"}
    assert kwargs["Cs"] == 120.0
    assert parameters.as_dict() == {"goal": list(parameters.goal), **kwargs}


def test_runtime_options_extend_the_kwargs():
    parameters = UsvNavigationParameters(goal=(1.0, 2.0), speed=3.0, safety_radius=4.0, control_horizon=5.0, runtime_options=(("K", 0.4),))
    assert parameters.runtime_kwargs()["K"] == 0.4
