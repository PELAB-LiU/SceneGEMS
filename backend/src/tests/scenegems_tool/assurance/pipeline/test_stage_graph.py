"""The stage graph: steps, keys, priorities, and a case's stage and readiness from its progress."""

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict
from scenegems_tool.assurance.pipeline.stage_graph import SCENE_STEP, TRAJECTORIES_STEP, CaseProgress, StageGraph, Step
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage
from tests.scenegems_tool.assurance.pipeline.conftest import config_dict

SIMULATE, MONITOR, CALIBRATE = PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE


def _graph(*runs) -> StageGraph:
    return StageGraph(campaign_config_from_dict(config_dict(runs=list(runs))))


def test_steps_name_their_stage_run_and_repeat():
    step = Step(SIMULATE, 1, 2)
    assert step.name == "simulate:1:2" and step.job_type == JobType.SIMULATION_KINEMATIC
    assert step.idempotency_key("c1", 42) == "campaign:c1:case:42:simulate:1:2"
    assert SCENE_STEP.idempotency_key("c1", 42) == "campaign:c1:case:42:generate_scene"
    assert Step(MONITOR, 0).name == "monitor:0" and Step(CALIBRATE, 3).job_type == JobType.CALIBRATION_DEVIATION
    with pytest.raises(ValueError):
        Step(SIMULATE, 0)
    with pytest.raises(ValueError):
        Step(PipelineStage.GENERATE_SCENE, 0)
    with pytest.raises(ValueError):
        Step(PipelineStage.VERDICT)


def test_later_stages_get_higher_priorities():
    priorities = [
        Step.of(stage, run, repeat).priority(10)
        for stage, run, repeat in [(PipelineStage.GENERATE_SCENE, None, None), (PipelineStage.GENERATE_TRAJECTORIES, None, None), (SIMULATE, 0, 0), (MONITOR, 0, None), (CALIBRATE, 0, None)]
    ]
    assert priorities == sorted(priorities) and priorities[0] == 10 and len(set(priorities)) == 5


def test_a_post_hoc_run_needs_a_monitor_job_and_its_verdict():
    graph = _graph({"monitor": "post_hoc"})
    progress = CaseProgress()
    assert graph.stage_of(progress) == PipelineStage.GENERATE_SCENE
    progress.mark(SCENE_STEP, "succeeded")
    progress.mark(TRAJECTORIES_STEP, "succeeded")
    assert graph.simulate_steps() == [Step(SIMULATE, 0, 0)]
    assert graph.stage_of(progress) == SIMULATE
    progress.mark(Step(SIMULATE, 0, 0), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 0) == [Step(MONITOR, 0)]
    assert graph.stage_of(progress) == MONITOR and not graph.ready(progress)
    progress.mark(Step(MONITOR, 0), "succeeded")
    progress.run(0)["verdict"] = {"state": "passed"}
    assert graph.stage_of(progress) == PipelineStage.VERDICT and graph.ready(progress)


@pytest.mark.parametrize("monitor", ["live", "empty"])
def test_live_and_empty_monitors_run_no_monitor_job(monitor):
    graph = _graph({"monitor": monitor})
    progress = CaseProgress({"steps": {"generate_scene": "succeeded", "generate_trajectories": "succeeded", "simulate:0:0": "succeeded"}})
    assert graph.steps_after_simulation(progress, 0, 0) == []
    assert graph.stage_of(progress) == PipelineStage.VERDICT


def test_repeats_simulate_each_and_calibrate_once_all_are_in():
    graph = _graph({"monitor": "empty", "repeats": 3}, {"monitor": "post_hoc"})
    assert graph.simulate_steps() == [Step(SIMULATE, 0, 0), Step(SIMULATE, 0, 1), Step(SIMULATE, 0, 2), Step(SIMULATE, 1, 0)]
    progress = CaseProgress({"steps": {"generate_scene": "succeeded", "generate_trajectories": "succeeded"}})
    progress.mark(Step(SIMULATE, 0, 2), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 2) == []
    progress.mark(Step(SIMULATE, 0, 0), "succeeded")
    progress.mark(Step(SIMULATE, 0, 1), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 1) == [Step(CALIBRATE, 0)]
    progress.mark(Step(SIMULATE, 1, 0), "succeeded")
    progress.run(0)["verdict"] = {"state": "unmonitored"}
    assert graph.stage_of(progress) == MONITOR  # run 1's post-hoc monitor first
    progress.mark(Step(MONITOR, 1), "succeeded")
    progress.run(1)["verdict"] = {"state": "passed"}
    assert graph.stage_of(progress) == CALIBRATE and not graph.ready(progress)
    progress.mark(Step(CALIBRATE, 0), "succeeded")
    progress.run(0)["calibrated"] = True
    assert graph.ready(progress)


def test_progress_round_trips_through_json():
    progress = CaseProgress()
    progress.mark(SCENE_STEP, "succeeded")
    progress.set_run_record(0, 1, 17)
    progress.set_run_record(0, 0, 16)
    again = CaseProgress(progress.to_json())
    assert again.handled(SCENE_STEP) and again.run_record_id(0, 1) == 17 and sorted(again.run_record_ids()) == [16, 17]
    assert again.pending_verdict(0) is None
