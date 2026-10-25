"""The generated per-job ArduPilot stack, checked as compose content without Docker."""

import os

import pytest

from scenegems_tool.cluster.node import instance_scope
from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs.simulation_ardupilot_job import STACK_NETWORK, ArduPilotSimulationPayload, build_job_stack
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE
from scenegems_tool.cluster.protocol.jobs import JobType
from utils.file_system_utils import RUNTIME_ASSETS_VOLUME

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


@pytest.fixture
def instances_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(instance_scope, "INSTANCES_FOLDER", str(tmp_path).replace("\\", "/"))
    monkeypatch.delenv("SCENARIO_EXECUTION_IMAGE", raising=False)
    return tmp_path


def stack_for(layer, node, make_job, head_on_trajectories, job_id="sim-1"):
    payload_data = {"simulation_layer": layer, "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE}
    job = make_job(JobType.SIMULATION_ARDUPILOT, payload_data, job_id=job_id)
    return job, build_job_stack(job, node, ArduPilotSimulationPayload.model_validate(payload_data))


@pytest.mark.parametrize("layer", ["ardupilot_sim", "gazebo"])
def test_stack_is_scoped_to_the_job(instances_folder, node, make_job, head_on_trajectories, layer):
    job, stack = stack_for(layer, node, make_job, head_on_trajectories)
    scope = node.job_scope(job)
    services = stack.compose["services"]
    vessel_services = [key for key in services if key.startswith("vessel_")]
    assert sorted(vessel_services) == ["vessel_0", "vessel_1"]
    for key, service in services.items():
        assert service["container_name"] == scope.container_name(key)
        assert "ports" not in service and "restart" not in service
    runner = services[RUNNER_SERVICE]
    assert runner["image"] == "scenegems-scenario-execution-subsystem:latest"
    assert runner["networks"] == [STACK_NETWORK]
    assert set(runner["depends_on"]) == set(services) - {RUNNER_SERVICE}
    # The stack network has no fixed name, so compose scopes it by the project name.
    assert stack.compose["networks"] == {STACK_NETWORK: {"driver": "bridge"}}
    assert stack.compose["volumes"] == {RUNTIME_ASSETS_VOLUME: {"external": True}}
    assert stack.project.name == scope.compose_project
    if layer == "gazebo":
        assert "gazebo" in services
    else:
        assert "gazebo" not in services


def test_generated_files_go_to_the_job_folder(instances_folder, node, make_job, head_on_trajectories):
    job, stack = stack_for("gazebo", node, make_job, head_on_trajectories)
    gen_folder = f"{node.job_scope(job).folder}/gen"
    assert sorted(os.listdir(gen_folder)) == ["ocean_world.sdf", "params-vessel_0.params", "params-vessel_1.params", "trajectories.json", "vessel_0_model.sdf", "vessel_1_model.sdf"]
    sitl_environment = stack.compose["services"]["vessel_0"]["environment"]
    assert any(entry.startswith("SITL_PARAM_FILE=") and entry.endswith(f"{gen_folder}/params-vessel_0.params") for entry in sitl_environment)
    assert stack.compose["services"]["gazebo"]["environment"]["WORLD_SDF"].endswith(f"{gen_folder}/ocean_world.sdf")


def test_two_jobs_get_disjoint_stacks(instances_folder, node, make_job, head_on_trajectories):
    _, first = stack_for("ardupilot_sim", node, make_job, head_on_trajectories, job_id="a")
    _, second = stack_for("ardupilot_sim", node, make_job, head_on_trajectories, job_id="b")
    first_names = {service["container_name"] for service in first.compose["services"].values()} | {first.project.name}
    second_names = {service["container_name"] for service in second.compose["services"].values()} | {second.project.name}
    assert not first_names & second_names


def test_unavailable_stack_fails_for_good(instances_folder, node, make_job, head_on_trajectories):
    payload_data = {"simulation_layer": "ardupilot_sim", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, "speedup": 1000}
    job = make_job(JobType.SIMULATION_ARDUPILOT, payload_data)
    with pytest.raises(JobFailed) as failure:
        build_job_stack(job, node, ArduPilotSimulationPayload.model_validate(payload_data))
    assert not failure.value.retryable
