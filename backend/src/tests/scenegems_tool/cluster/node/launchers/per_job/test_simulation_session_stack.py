"""The workbench's interactive simulation stack: its fixed names, its networks and the ground station ports it reports."""

import subprocess
import threading

from scenegems_tool.cluster.node.launchers import compose_project
from scenegems_tool.cluster.node.launchers.per_job.simulation_session_stack import (
    COMPOSE_PROJECT,
    SERVICE_NAME,
    TRAJECTORIES_GEN_FILE,
    SimulationSessionStack,
    build_unified_compose,
    ground_control_services,
)
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselStackConfig
from tests.scenegems_tool.vessel_stack.scenarios import stack_instance
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


def _unified(stack, config):
    connection = MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False)
    return build_unified_compose(stack, connection, Geofence(57.7, 11.9, 2000.0), config, 1)


def test_the_scenario_execution_service_joins_the_vessel_network_to_drive_the_lockstep_runners():
    stack = {"services": {"vessel_0": {"image": "sitl", "networks": ["maritime_net"]}}, "networks": {"maritime_net": {"driver": "bridge"}}}
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.ARDUPILOT_SIM, environment=EnvironmentConfig.calm())
    assert "maritime_net" in _unified(stack, config)["services"][SERVICE_NAME]["networks"]


def test_a_kinematic_instance_runs_the_scenario_execution_service_alone():
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.KINEMATIC, environment=EnvironmentConfig.calm())
    compose = _unified({"services": {}, "networks": {}}, config)
    assert list(compose["services"]) == [SERVICE_NAME]
    assert "depends_on" not in compose["services"][SERVICE_NAME]


def test_mission_planner_vessels_on_their_ground_station_port_are_found_by_their_mavproxy():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1])
    operated = instance.vessels["1"]
    operated.stack = VesselStackConfig(AsvSoftwareId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    assert ground_control_services(instance) == {"1": "agent_1_mavproxy"}
    operated.adapter_ids = ("mission_planner_mavlink_port",)
    assert ground_control_services(instance) == {}, "ArduAgent's external mode forwards to a fixed UDP port instead"


class FakeProject:
    def __init__(self, ports):
        self.ports = ports
        self.asked = []

    def published_port(self, service, container_port):
        self.asked.append((service, container_port))
        return self.ports.get(service)


def test_the_published_ground_station_ports_are_reported_by_agent_id():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], asv_software=AsvSoftwareId.MISSION_PLANNER)
    reported = []
    stack = SimulationSessionStack.__new__(SimulationSessionStack)
    stack.project = FakeProject({"agent_0_mavproxy": 49153})
    stack._on_ground_control_ports = reported.append
    stack._shutdown = threading.Event()
    stack._report_ground_control_ports(instance)
    assert reported == [{"0": 49153}]
    assert stack.project.asked == [("agent_0_mavproxy", 5770)]


def test_published_port_reads_the_host_port_compose_prints(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="0.0.0.0:49153\n", stderr="")

    monkeypatch.setattr(compose_project.subprocess, "run", fake_run)
    project = compose_project.ComposeProject("p", "/tmp/compose.yml")
    assert project.published_port("agent_0_mavproxy", 5770) == 49153
    assert calls[0][-3:] == ["port", "agent_0_mavproxy", "5770"]
    monkeypatch.setattr(compose_project.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="no port"))
    assert project.published_port("agent_0_mavproxy", 5770) is None
