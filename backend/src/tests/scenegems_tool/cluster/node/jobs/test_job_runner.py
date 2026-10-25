import pytest

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import job_runner
from scenegems_tool.cluster.node.jobs.job_types import JOB_TYPE_MODULES
from scenegems_tool.cluster.protocol.jobs import JobType


def test_every_job_type_has_a_module_with_a_runner():
    assert set(JOB_TYPE_MODULES) == set(JobType)
    for module in JOB_TYPE_MODULES.values():
        assert callable(module.run)


def test_runner_container_job_types_have_an_in_container_part():
    for job_type in (JobType.SIMULATION_KINEMATIC, JobType.SIMULATION_ARDUPILOT, JobType.MONITORING_POST_HOC):
        assert callable(JOB_TYPE_MODULES[job_type].execute)


def test_run_job_dispatches_to_the_job_type(monkeypatch, node, make_job):
    calls = []
    module = JOB_TYPE_MODULES[JobType.SIMULATION_KINEMATIC]
    monkeypatch.setattr(module, "run", lambda job, node, report, cancel: calls.append((job.job_id, report, cancel)) or {"ok": True})
    assert job_runner.run_job(make_job(JobType.SIMULATION_KINEMATIC, {}), node, "report") == {"ok": True}
    assert calls == [("job-1", "report", None)]


def test_run_job_refuses_a_type_the_node_has_no_slots_for(node, make_job):
    with pytest.raises(JobFailed):
        job_runner.run_job(make_job(JobType.MONITORING_POST_HOC, {}), node, report=None)
