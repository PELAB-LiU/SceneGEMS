import pytest

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.per_job.job_container_io import JOB_CONTAINER_MAIN
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service, scope_services

SCOPE = InstanceScope.per_job("m1", "n1", "j7-1")


def test_runner_without_networks_has_no_network():
    service = runner_service("scenegems-scenario-execution-subsystem:latest")
    assert service["command"] == ["python", "-m", JOB_CONTAINER_MAIN]
    assert service["network_mode"] == "none"
    assert "networks" not in service


def test_runner_on_a_stack_network_waits_for_the_stack():
    service = runner_service("image", networks=["maritime_net"], depends_on=["vessel_0", "vessel_1"])
    assert service["networks"] == ["maritime_net"]
    assert service["depends_on"] == ["vessel_0", "vessel_1"]
    assert "network_mode" not in service


def test_scoped_services_get_scope_names_and_no_published_ports():
    services = scope_services(SCOPE, {"gazebo": {"image": "gz", "container_name": "gazebo", "ports": ["11345:11345"], "restart": "unless-stopped"}})
    assert services["gazebo"] == {"image": "gz", "container_name": "scenegems-m1-n1-job-j7-1-gazebo"}


def test_job_stack_names_the_runner_container_by_scope():
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    assert stack.runner_container == "scenegems-m1-n1-job-j7-1-runner"
    assert stack.project.name == SCOPE.compose_project
    assert stack.project.compose_filename == f"{SCOPE.folder}/docker-compose.yml"


def test_job_stack_needs_a_runner():
    with pytest.raises(ValueError):
        JobStack(SCOPE, {"gazebo": {"image": "gz"}})
