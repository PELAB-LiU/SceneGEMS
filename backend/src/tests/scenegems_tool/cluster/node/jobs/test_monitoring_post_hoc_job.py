"""monitoring.post_hoc in process: the result shape the pipeline reads, and frames on request."""

import pytest

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import monitoring_post_hoc_job
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
