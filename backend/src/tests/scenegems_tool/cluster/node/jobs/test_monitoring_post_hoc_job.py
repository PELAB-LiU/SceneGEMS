"""monitoring.post_hoc in process: the result shape the pipeline reads, frames on request, and a scene judged as a one-scene log."""

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import monitoring_post_hoc_job
from scenegems_tool.cluster.node.jobs.job_payload import validate_structure
from scenegems_tool.cluster.protocol.jobs import JobType


def _quiet(message, progress=None):
    pass


def test_the_result_summarizes_the_rules(make_job, head_on_trajectories):
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict()}), _quiet)
    assert set(result) == {"scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed"}
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
    assert not result["passed"]
    assert {(item["rule"], item["first_failed_at"]) for item in result["failed_rules"]} == {
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (OS_0)", 61),
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (TS_1)", 61),
    }
    for item in result["failed_rules"]:
        assert result["rules"][item["relation"]][item["rule"]]["failed"] == item["first_failed_at"]


def test_frames_are_added_on_request(make_job, head_on_trajectories):
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict(), "include_frames": True, "scenario_id": "case-1"}), _quiet)
    assert len(result["frames"]) == result["monitored_scenes"]


def test_an_unresolved_state_log_fails_for_good(make_job):
    job = make_job(JobType.MONITORING_POST_HOC, {"trajectories": {"sha256": "ab" * 32, "size_bytes": 1, "kind": "trajectories"}})
    with pytest.raises(JobFailed) as failure:
        monitoring_post_hoc_job.execute(job, _quiet)
    assert not failure.value.retryable


def _scene(head_on_trajectories):
    return head_on_trajectories.scene_list[0].to_dict()


@pytest.mark.parametrize("document", ["evaluation_data", "scene", "initial_scene"])
def test_a_scene_is_judged_as_a_one_scene_log(make_job, head_on_trajectories, document):
    scene = _scene(head_on_trajectories)
    payload = {"scene": {"best_scene": scene, "random_seed": 3} if document == "evaluation_data" else (scene if document == "scene" else {"initial_scene": scene})}
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, payload), _quiet)
    assert set(result) == {"scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed"}
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (1, 1, 1)
    # the initial situation alone: no rule has an outcome yet (they need the motion over time), so nothing fails
    assert result["passed"] and result["failed_rules"] == [] and isinstance(result["rules"], dict)


def test_a_scene_gets_its_frame_on_request(make_job, head_on_trajectories):
    payload = {"scene": _scene(head_on_trajectories), "include_frames": True, "scenario_id": "case-1#scene"}
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, payload), _quiet)
    assert len(result["frames"]) == result["monitored_scenes"] == 1


@pytest.mark.parametrize("payload", [{}, {"trajectories": "both", "scene": "both"}])
def test_exactly_one_of_trajectories_and_scene(head_on_trajectories, payload):
    if payload:
        payload = {"trajectories": head_on_trajectories.to_dict(), "scene": _scene(head_on_trajectories)}
    with pytest.raises(ValidationError, match="exactly one of trajectories and scene"):
        validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, payload)


def test_a_scene_reference_is_checked_for_shape_and_must_be_resolved(make_job):
    reference = {"sha256": "cd" * 32, "size_bytes": 1, "kind": "scene"}
    validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, {"scene": reference})
    with pytest.raises(JobFailed) as failure:
        monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": reference}), _quiet)
    assert not failure.value.retryable


def test_a_document_without_a_scene_fails_for_good(make_job):
    with pytest.raises(JobFailed, match="holds no scene") as failure:
        monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": {"random_seed": 3}}), _quiet)
    assert not failure.value.retryable
