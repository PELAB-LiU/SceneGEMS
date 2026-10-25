"""The workbench's interactive simulation stack keeps its fixed names."""

from scenegems_tool.cluster.node.launchers.per_job.simulation_session_stack import COMPOSE_PROJECT, SERVICE_NAME, TRAJECTORIES_GEN_FILE, build_unified_compose
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig
from utils.file_system_utils import docker_volume_path


def test_unified_compose_keeps_the_workbench_names(monkeypatch):
    monkeypatch.delenv("SCENARIO_EXECUTION_IMAGE", raising=False)
    monkeypatch.delenv("SCENEGEMS_DOCKER_NETWORK", raising=False)
    stack = {"services": {"vessel_0": {"image": "sitl", "networks": ["maritime_net"]}}, "networks": {"maritime_net": {"driver": "bridge"}}}
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.ARDUPILOT_SIM, environment=EnvironmentConfig.calm())
    connection = MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False)
    compose = build_unified_compose(stack, connection, Geofence(57.7, 11.9, 2000.0), config, 1)

    assert COMPOSE_PROJECT == "scenegems-scenario-execution-subsystem"
    service = compose["services"][SERVICE_NAME]
    assert service["container_name"] == service["hostname"] == "scenario_execution"
    assert service["image"] == "scenegems-scenario-execution-subsystem:latest"
    assert service["depends_on"] == ["vessel_0"]
    assert service["environment"]["TRAJECTORIES_PATH"] == docker_volume_path(TRAJECTORIES_GEN_FILE)
    assert "MQTT_TOPIC_PREFIX" not in service["environment"]
    assert list(compose["services"]) == ["vessel_0", SERVICE_NAME]
    assert list(compose["networks"]) == ["scenario_execution_net", "maritime_net", "scenegems_broker"]
