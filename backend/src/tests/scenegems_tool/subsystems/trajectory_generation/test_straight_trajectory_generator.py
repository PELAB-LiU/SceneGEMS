"""The straight trajectory generator: straight on from the initial scene up to the timespan."""

from scenegems_tool.subsystems.trajectory_generation.straight_trajectory_generator import DEFAULT_TIMESPAN_S, STRAIGHT_ALGORITHM, straight_trajectory_data
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories


def test_every_vessel_holds_its_initial_heading_and_speed():
    scene = encounter_trajectories("head_on", 60).initial_scene
    data = straight_trajectory_data(scene, 10, 300, "head_on", seed=5)
    trajectories = data.trajectories
    assert trajectories.time_step == 10 and trajectories.timespan == 300
    assert (data.algorithm_desc, data.config_name, data.random_seed) == (STRAIGHT_ALGORITHM, "head_on", 5)
    for vessel in scene.vessels:
        states = trajectories.state_list(vessel)
        assert {(state.heading, state.speed) for state in states} == {(scene[vessel].heading, scene[vessel].speed)}
        assert states[0] == scene[vessel]


def test_the_timespan_is_rounded_up_to_a_step_and_defaults_to_an_hour():
    scene = encounter_trajectories("head_on", 60).initial_scene
    assert straight_trajectory_data(scene, 15, 100, "x", None).trajectories.timespan == 105
    assert straight_trajectory_data(scene, 15, None, "x", None).trajectories.timespan == DEFAULT_TIMESPAN_S
