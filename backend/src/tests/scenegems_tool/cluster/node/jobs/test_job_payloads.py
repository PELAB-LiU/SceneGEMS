"""Payload validation of every job type: bad payloads fail for good before any container starts."""

import pytest

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.jobs.monitoring_post_hoc_job import PostHocMonitoringPayload
from scenegems_tool.cluster.node.jobs.scene_generation_job import SceneGenerationPayload
from scenegems_tool.cluster.node.jobs.simulation_ardupilot_job import ArduPilotSimulationLayer, ArduPilotSimulationPayload
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode, KinematicSimulationPayload
from scenegems_tool.cluster.node.jobs.trajectory_generation_job import TrajectoryGenerationPayload
from scenegems_tool.cluster.protocol.jobs import JobType
from utils.file_system_utils import FUNCTIONAL_MODELS_FOLDER

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


@pytest.fixture
def trajectories(head_on_trajectories):
    return head_on_trajectories.to_dict()


def test_kinematic_payload_defaults(trajectories):
    payload = KinematicSimulationPayload.model_validate({"trajectories": trajectories})
    assert payload.mode == KinematicMode.REPLAY
    assert (payload.dt, payload.steps, payload.seed, payload.include_trajectories) == (None, None, 0, True)


def test_kinematic_closed_loop_payload_with_parameters(trajectories):
    payload = KinematicSimulationPayload.model_validate(
        {"mode": "usv_navigation", "trajectories": trajectories, "own_ship_id": 0, "usv_navigation": {"goal": [2000.0, 0.0], "speed": 8.0, "safety_radius": 120.0, "control_horizon": 60.0}}
    )
    parameters = payload.usv_navigation.to_parameters()
    assert parameters.goal == (2000.0, 0.0)
    assert parameters.prescribed_time == 3.0


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "replay", "own_ship_id": 0},
        {"mode": "teleport"},
        {"dt": 0},
        {"steps": 0},
        {"unknown_field": 1},
        {"trajectories": {"time_step": 1}},
        {"trajectories": {"time_step": 1, "scene_list": []}},
    ],
)
def test_invalid_kinematic_payloads_are_rejected(trajectories, change):
    with pytest.raises(ValueError):
        KinematicSimulationPayload.model_validate({"trajectories": trajectories, **change})


def test_ardupilot_payload(trajectories):
    payload = ArduPilotSimulationPayload.model_validate({"simulation_layer": "gazebo", "trajectories": trajectories, "geofence": GEOFENCE, "speedup": 5})
    assert payload.simulation_layer == ArduPilotSimulationLayer.GAZEBO
    assert payload.geofence.to_geofence().radius_meters == 2000.0


@pytest.mark.parametrize("change", [{"simulation_layer": "kinematic"}, {"speedup": 0}, {"geofence": {**GEOFENCE, "latitude": 91.0}}, {"geofence": None}])
def test_invalid_ardupilot_payloads_are_rejected(trajectories, change):
    with pytest.raises(ValueError):
        ArduPilotSimulationPayload.model_validate({"simulation_layer": "ardupilot_sim", "trajectories": trajectories, "geofence": GEOFENCE, **change})


def test_post_hoc_payload_defaults(trajectories):
    payload = PostHocMonitoringPayload.model_validate({"trajectories": trajectories})
    assert payload.colregs_constraints_content is None
    assert not payload.include_frames


def test_trajectory_generation_params_are_checked():
    base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    TrajectoryGenerationPayload.model_validate({**base, "params": {"maxIterations": 100, "timeout": 30}})
    with pytest.raises(ValueError):
        TrajectoryGenerationPayload.model_validate({**base, "params": {"max_iterations": 100}})
    with pytest.raises(ValueError):
        TrajectoryGenerationPayload.model_validate({**base, "params": {"maxIterations": "many"}})


def test_scene_generation_payload_parses_the_functional_scenario():
    with open(f"{FUNCTIONAL_MODELS_FOLDER}/all/2vessel_0obstacle_scenarios/functional_model0.problem", encoding="utf-8") as file:
        problem = file.read()
    contents = {"colregs_constraints_content": "", "vessel_types_content": "", "obstacle_types_content": ""}
    assert SceneGenerationPayload.model_validate({"functional_scenario_content": problem, **contents}).timeout_s == 60
    with pytest.raises(ValueError):
        SceneGenerationPayload.model_validate({"functional_scenario_content": "class {", **contents})


def test_parse_payload_turns_validation_errors_into_final_failures(make_job):
    job = make_job(JobType.SIMULATION_KINEMATIC, {"trajectories": {}})
    with pytest.raises(JobFailed) as failure:
        parse_payload(KinematicSimulationPayload, job)
    assert not failure.value.retryable
    assert "simulation.kinematic" in str(failure.value)
