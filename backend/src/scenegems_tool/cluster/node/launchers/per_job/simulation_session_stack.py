"""The workbench's simulation stack: one compose stack per simulation session.

It holds the generated vessel stack (SITL, MAVProxy, ArduAgent, Gazebo) and the scenario
execution service, which the workbench drives over WARA-PS MQTT. There is one such stack
per machine with fixed names, because ArduAgent publishes unscoped WARA-PS topics; the
node runs simulations as scoped per-job stacks instead (per_job/job_stack.py).

The scenario execution service joins the vessel stack's network, since an instance of
simulated vessels is driven by its lockstep runner over MAVLink or gz-transport from there
(subsystems/scenario_execution/lockstep_simulation_driver.py). A kinematic instance has no
simulator services: the service runs it alone. Once the stack is up, the host port Docker
published for each Mission Planner vessel's ground control station is read back and handed
to on_ground_control_ports.

A new session takes ownership of the stack; a teardown scheduled by an older owner is
skipped, so replacing a session never removes the stack its successor just started.
"""

import base64
import json
import logging
import os
import threading
from typing import Callable, Dict, Optional

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.cluster.node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.node.launchers.docker_cli import container_ids_for_compose_project, force_remove_compose_project
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.gateway.protocol import make_simulation_models_body
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_scenario_execution_service import SCENARIO_EXECUTION_SERVICE_TOPIC
from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import GCS_CONTAINER_PORT, MISSION_PLANNER_GCS_PORT
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import gcs_mavproxy_service_name
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.simulation_docker_stack import SIMULATION_COMPOSE_PROJECT, build_simulation_docker_stack_artifacts, write_simulation_gen_files
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import SCENARIO_EXECUTION_GEN_FOLDER, docker_volume_path, merge_compose_volumes, runtime_assets_volume_mount

COMPOSE_PROJECT = "scenegems-scenario-execution-subsystem"
SERVICE_NAME = "scenario_execution"
SERVICE_CPU = 2
TRAJECTORIES_GEN_FILE = f"{SCENARIO_EXECUTION_GEN_FOLDER}/trajectories.json"
GROUND_CONTROL_PORT_ATTEMPTS = 30  # seconds to wait for Docker to publish the ground station ports after up
GroundControlPortsObserver = Callable[[Dict[str, int]], None]  # host port by agent id
_logger = logging.getLogger(__name__)
_stack_lock = threading.Lock()
_stack_generation = 0
_stack_generation_lock = threading.Lock()


def claim_stack_ownership() -> int:
    """Mark a new stack owner; stale scheduled destroys for older generations are ignored."""
    global _stack_generation
    with _stack_generation_lock:
        _stack_generation += 1
        return _stack_generation


def force_destroy_scenario_execution_stack(compose_filename: str | None = None) -> None:
    """Fast teardown: force-remove containers by compose project label (no blocking compose down)."""
    del compose_filename
    force_remove_compose_project(COMPOSE_PROJECT)
    force_remove_compose_project(SIMULATION_COMPOSE_PROJECT)


def schedule_force_destroy_scenario_execution_stack(
    compose_filename: str | None = None,
    owner_generation: int | None = None,
) -> None:
    """Tear down the scenario-execution stack on a background thread without blocking the caller."""

    def _run_destroy() -> None:
        try:
            with _stack_generation_lock:
                if owner_generation is not None and owner_generation != _stack_generation:
                    return
            with _stack_lock:
                force_destroy_scenario_execution_stack(compose_filename)
        except BaseException:
            _logger.exception("Background scenario execution stack destroy failed")

    threading.Thread(
        target=_run_destroy,
        name="scenario_execution_force_destroy",
        daemon=True,
    ).start()


class SimulationSessionStack:
    """Spawns and tears down the unified scenario-execution Docker Compose stack."""

    service_topic = SCENARIO_EXECUTION_SERVICE_TOPIC

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
        on_ground_control_ports: Optional[GroundControlPortsObserver] = None,
    ):
        self.project = ComposeProject(COMPOSE_PROJECT, f"{SCENARIO_EXECUTION_GEN_FOLDER}/docker-compose.yml")
        self._on_ground_control_ports = on_ground_control_ports
        self.compose_filename = self.project.compose_filename
        self._destroyed = False
        self._shutdown = threading.Event()
        self._stack_generation = claim_stack_ownership()
        self._spawn_thread = threading.Thread(
            target=self._run_spawn,
            args=(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step),
            name="scenario_execution_compose_spawn",
            daemon=True,
        )
        self._spawn_thread.start()

    def _run_spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        try:
            if self._shutdown.is_set():
                return
            with _stack_lock:
                if self._shutdown.is_set():
                    return
                if container_ids_for_compose_project(COMPOSE_PROJECT):
                    force_destroy_scenario_execution_stack()
                if self._shutdown.is_set():
                    return
            self._spawn(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step)
        except BaseException:
            _logger.exception("Scenario execution stack spawn failed")
            force_destroy_scenario_execution_stack()

    def _spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        if simulation_config.simulation_layer == SimulationLayerId.KINEMATIC:
            # The worker integrates the kinematic layer itself; it only needs the trajectories.
            pending_writes = [(TRAJECTORIES_GEN_FILE, json.dumps(trajectories.to_dict()))]
            stack_compose: dict = {"services": {}, "networks": {}}
        else:
            pending_writes, stack_compose = build_simulation_docker_stack_artifacts(
                simulation_config,
                trajectories,
                mqtt_connection,
                reference_geofence,
                embedded_in_subsystem=True,
            )
        write_simulation_gen_files(pending_writes)
        self._verify_gen_files(pending_writes)

        unified_compose = build_unified_compose(stack_compose, mqtt_connection, reference_geofence, simulation_config, time_step)
        self.project.write(unified_compose)
        self.project.up("--force-recreate")
        self._report_ground_control_ports(simulation_config)

    def _report_ground_control_ports(self, simulation_config: SimulationInstanceConfig) -> None:
        services = ground_control_services(simulation_config)
        if not services or self._on_ground_control_ports is None:
            return
        ports: Dict[str, int] = {}
        for _ in range(GROUND_CONTROL_PORT_ATTEMPTS):
            for agent_id, service in services.items():
                if agent_id not in ports:
                    port = self.project.published_port(service, GCS_CONTAINER_PORT)
                    if port is not None:
                        ports[agent_id] = port
            if len(ports) == len(services) or self._shutdown.wait(1.0):
                break
        if ports and not self._shutdown.is_set():
            self._on_ground_control_ports(ports)

    def _verify_gen_files(self, pending_writes: list[tuple[str, str]]) -> None:
        missing = [path for path, _ in pending_writes if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(f"Simulation gen files missing before compose up: {missing}")

    def cancel(self) -> None:
        """Stop spawn without tearing down the shared Docker stack (session replace)."""
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()
        schedule_force_destroy_scenario_execution_stack(
            self.compose_filename,
            owner_generation=self._stack_generation,
        )


def ground_control_services(simulation_config: SimulationInstanceConfig) -> Dict[str, str]:
    """The MAVProxy service of every Mission Planner vessel on its ground control station port, by agent id."""
    resolver = default_resolver()
    services = {}
    for agent_id, vessel in simulation_config.simulated_vessels.items():
        adapter = resolver.resolve(vessel.stack, vessel.adapter_ids).asv_adapter
        if adapter is not None and adapter.id == MISSION_PLANNER_GCS_PORT.id:
            services[agent_id] = gcs_mavproxy_service_name(vessel.require_connection().agent_name)
    return services


def build_unified_compose(
    stack_compose: dict,
    mqtt_connection: MQttConnectionInfo,
    reference_geofence: Geofence,
    simulation_config: SimulationInstanceConfig,
    time_step: int,
) -> dict:
    """The vessel stack's services plus the scenario execution service that drives them."""
    simulation_config_b64 = base64.b64encode(json.dumps(make_simulation_models_body(simulation_config)).encode("utf-8")).decode("ascii")

    agent_service_names = list(stack_compose["services"].keys())
    scenario_execution_service = {
        "image": subsystem_image(Subsystem.SCENARIO_EXECUTION),
        "container_name": SERVICE_NAME,
        "hostname": SERVICE_NAME,
        **({"depends_on": agent_service_names} if agent_service_names else {}),
        "environment": {
            **subsystem_environment(mqtt_connection, reference_geofence),
            "SIMULATION_CONFIG_JSON_B64": simulation_config_b64,
            "TRAJECTORIES_PATH": docker_volume_path(TRAJECTORIES_GEN_FILE),
            "TIME_STEP": str(time_step),
        },
        "cpus": SERVICE_CPU,
        "restart": "unless-stopped",
        "extra_hosts": ["host.docker.internal:host-gateway"],
        "volumes": [runtime_assets_volume_mount(read_only=True)],
        # The vessel stack's network too: the lockstep runners reach SITL and Gazebo there.
        "networks": ["scenario_execution_net", *stack_compose.get("networks", {})],
    }

    return merge_compose_volumes(
        attach_broker_network_to_compose(
            {
                "services": {
                    **stack_compose["services"],
                    SERVICE_NAME: scenario_execution_service,
                },
                "networks": {
                    "scenario_execution_net": {"driver": "bridge"},
                    **stack_compose.get("networks", {}),
                },
            }
        )
    )
