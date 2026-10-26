"""The generated per-job ArduPilot stack, checked as compose content without Docker."""

import os

import pytest

from scenegems_tool.cluster.node import instance_scope
from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs.in_container.run_observation import RunObserver
from scenegems_tool.cluster.node.jobs.simulation_ardupilot_job import STACK_NETWORK, ArduPilotSimulationPayload, build_job_stack, execute
from scenegems_tool.cluster.node.launchers.per_job.job_container_io import ObservationControl
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import StampedState
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import MavlinkRunResult
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


def test_an_observed_run_forwards_its_lockstep_states_at_the_stacks_own_pace(monkeypatch, make_job, head_on_trajectories):
    """SITL runs free, so the run is not slowed down; its frames are decimated by its speedup and the result is unchanged."""
    from scenegems_tool.vessel_stack.control_layers.ardupilot import mavlink_lockstep_runner

    vessels = head_on_trajectories.initial_scene.vessels
    columns = {vessel.id: head_on_trajectories.state_list(vessel) for vessel in vessels}

    def replay(trajectories, instance, geofence, *, dt, steps, start_boot_s, on_step=None):
        recorded = []
        for index in range(len(columns[0])):
            samples = {vessel_id: StampedState(boot_ms=100_000 + index * 1000, state=column[index]) for vessel_id, column in columns.items()}
            recorded.append(tuple(samples[vessel_id] for vessel_id in sorted(samples)))
            if on_step is not None:
                on_step(index, samples)
        return MavlinkRunResult((0, 1), 1.0, 0, (), (100_000, 100_000), tuple(recorded), (), 12.0, {"steps": len(recorded) - 1})

    monkeypatch.setattr(mavlink_lockstep_runner, "run_mavlink_replay", replay)
    job = make_job(JobType.SIMULATION_ARDUPILOT, {"simulation_layer": "ardupilot_sim", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, "speedup": 50})
    plain = execute(job, lambda message, progress=None: None)
    frames, sleeps = [], []

    class Observation:
        def observer(self, build_frame, dt, **options):
            return RunObserver(lambda: ObservationControl(active=True, speed=10.0, revision=1), frames.append, build_frame, dt, sleep=sleeps.append, **options)

    assert execute(job, lambda message, progress=None: None, observation=Observation()) == plain
    assert sleeps == []  # not paced
    assert [frame["timestamp"] for frame in frames] == list(range(0, 121, 3))  # 50 steps a second at speedup 50: every third step
    last = frames[-1]
    assert last["scenarioId"] == job.job_id and set(last["statesByActorId"]) == {"0", "1"}
    assert last["statesByActorId"]["1"]["x"] == columns[1][120].x
