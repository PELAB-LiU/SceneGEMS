"""simulation.ardupilot: replay over the lockstep MAVLink adapter, on a SITL or Gazebo stack per job.

The node resolves the instance (every vessel replay to ardupilot on ardupilot_sim or gazebo,
through replay_mavlink_lockstep), generates the vessel stack into the job's folder and adds
a runner from the scenario execution image on the stack network. The runner drives every
vessel's SITL SERIAL0 (mavlink_lockstep_runner.run_mavlink_replay) and returns the run.

The generated files reach SITL and Gazebo through the runtime assets volume, so the caller
must run where that volume is mounted at RUNTIME_ASSETS_FOLDER: the node daemon's container
or the workbench backend's.
"""

import threading
from enum import Enum
from typing import Optional, Tuple

from pydantic import Field

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import GeofencePayload, TrajectoriesInput, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

STACK_NETWORK = "maritime_net"  # the network build_simulation_docker_stack_artifacts puts every vessel service on

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("states", ArtifactKind.TRAJECTORIES),)  # the state log


class ArduPilotSimulationLayer(str, Enum):
    ARDUPILOT_SIM = "ardupilot_sim"  # SITL's internal physics
    GAZEBO = "gazebo"  # SITL's JSON backend against a Gazebo world


class ArduPilotSimulationPayload(ProtocolModel):
    simulation_layer: ArduPilotSimulationLayer
    trajectories: TrajectoriesInput
    geofence: GeofencePayload  # maps the local frame to SITL's home positions
    speedup: int = Field(default=1, ge=1)  # requested SITL pace
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0
    start_boot_s: Optional[float] = Field(default=None, ge=0.0)  # SITL time of scenario time 0; the next quantum when None
    include_states: bool = True  # return the observed state of every vessel at every step
    timeout_s: float = Field(default=1800.0, gt=0.0)


PAYLOAD_MODEL = ArduPilotSimulationPayload


def _instance(payload: ArduPilotSimulationPayload):
    from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import mavlink_replay_instance

    trajectories = to_trajectories(payload.trajectories)
    instance = mavlink_replay_instance(trajectories, SimulationLayerId(payload.simulation_layer.value), environment=EnvironmentConfig.calm(seed=payload.seed), speedup=payload.speedup)
    return trajectories, instance


def build_job_stack(job: JobSpec, node: NodeContext, payload: ArduPilotSimulationPayload) -> JobStack:
    """Resolve the instance, write the generated files into the job's folder and assemble the stack."""
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
    from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts, write_simulation_gen_files

    trajectories, instance = _instance(payload)
    try:
        default_resolver().require_instance(instance, attended=False)
    except StackUnavailableError as error:
        raise JobFailed(f"Simulation stack rejected: {error}", retryable=False) from error
    scope = node.job_scope(job)
    gen_folder = f"{scope.folder}/gen"
    pending_writes, stack_compose = build_simulation_docker_stack_artifacts(
        instance, trajectories, node.mqtt_connection, payload.geofence.to_geofence(), headless=True, embedded_in_subsystem=True, gen_folder=gen_folder
    )
    write_simulation_gen_files(pending_writes, gen_folder)
    vessel_services = list(stack_compose["services"])
    services = {
        **stack_compose["services"],
        RUNNER_SERVICE: runner_service(subsystem_image(Subsystem.SCENARIO_EXECUTION), networks=[STACK_NETWORK], depends_on=vessel_services),
    }
    return JobStack(scope, services, networks=stack_compose["networks"], volumes=stack_compose.get("volumes"))


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(ArduPilotSimulationPayload, job)
    report.status(f"generating the {payload.simulation_layer.value} stack")
    stack = build_job_stack(job, node, payload)
    return stack.run(job_document(job), report, timeout_s=payload.timeout_s, cancel=cancel)


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: drive every vessel's SITL in lockstep and describe the run."""
    from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import run_mavlink_replay

    payload = parse_payload(ArduPilotSimulationPayload, job)
    trajectories, instance = _instance(payload)
    status("connecting to SITL")
    result = run_mavlink_replay(trajectories, instance, payload.geofence.to_geofence(), dt=payload.dt, steps=payload.steps, start_boot_s=payload.start_boot_s)
    status("run finished", 1.0)
    data: JobResultData = {
        "run_record": dict(result.run_record),
        "steps": result.steps,
        "achieved_speedup": result.achieved_speedup,
        "state_digest": result.state_digest(),
    }
    if payload.include_states:
        # Per vessel id: one [sitl_ms, x, y, speed, heading] row per step from scenario time 0.
        data["states"] = {
            str(vessel_id): [[sample.boot_ms, sample.state.x, sample.state.y, sample.state.speed, sample.state.heading] for sample in column]
            for vessel_id, column in zip(result.vessel_ids, zip(*result.states))
        }
    return data
