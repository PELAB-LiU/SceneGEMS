"""TrajectoryGenerationParams: the generator choice in the wire form and the task form."""

import pytest

from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams, TrajectoryGeneratorId


def test_generator_and_timespan_travel_from_the_wire_to_the_task():
    params = TrajectoryGenerationParams.from_wire({"generator": "straight", "timespan": 900, "timeStep": 5})
    assert params == TrajectoryGenerationParams(time_step=5, generator=TrajectoryGeneratorId.STRAIGHT, timespan=900.0)
    task_params = params.to_wire()
    assert (task_params["generator"], task_params["timespan"]) == ("straight", 900.0)
    assert TrajectoryGenerationParams.from_task_params(task_params) == params


def test_without_a_generator_the_search_runs():
    params = TrajectoryGenerationParams.from_wire({})
    assert params.generator is None and params.generator_id == TrajectoryGeneratorId.MONITOR_DRIVEN_RRT
    assert TrajectoryGenerationParams.from_task_params(params.to_wire()) == params
    assert TrajectoryGenerationParams.from_task_params({}) == params  # a task from before the choice existed


@pytest.mark.parametrize("wire", [{"generator": "dijkstra"}, {"timespan": 0}, {"timespan": -1}])
def test_bad_choices_are_refused(wire):
    with pytest.raises(ValueError):
        TrajectoryGenerationParams.from_wire(wire)
