"""Repeats of a reference run on ArduPilot Sim and Gazebo stacks in Docker (needs Docker and the simulator images).

The stack of every repeat is generated with the project's own builder
(simulation_docker_stack.build_simulation_docker_stack_artifacts) from a mavlink_replay_instance,
so what is measured is what a campaign would start. This module only adapts the generated
compose file to run several repeats side by side on one host:

- the shared runtime assets volume becomes a bind mount of a folder per repeat, mounted at /runtime_assets
  (every host path in the generated files is rewritten to it);
- each SITL serial port is published on a host port of its own, which the MAVLink link connects to;
- fixed container names and the Gazebo host port are dropped, so repeats do not collide.

Two ways of driving a repeat are measured:

- replay: run_mavlink_replay, the lockstep adapter that replays the trajectory (design doc 12.8). Repeats are compared
  at equal scenario time. This is the number the resolver needs for replay_mavlink_lockstep.
- target: one position target far ahead on an engaged vessel, sampled against SITL time (design doc 10.5). Repeats are
  compared from the movement onset. This isolates the simulator and ArduPilot from the follower.

The resolver used for the run knows no stored measurements, so a speedup above today's measured limit is not refused
before it is measured.
"""

import copy
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from unittest import mock

import numpy as np
import yaml

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.calibration.measured_entry import MeasuredEntry, evidence, host_label
from scenegems_tool.vessel_stack.calibration.reference_scenarios import REFERENCE_RUNS, reference_run
from scenegems_tool.vessel_stack.calibration.repeat_analysis import DeviationSummary, TrackSamples, achieved_speedup, repeat_deviation
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import MavlinkLink
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import MavlinkRunResult, mavlink_replay_instance, run_mavlink_replay
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_specs import ARDUPILOT_SIM_LAYER, SITL_INTERNAL_PHYSICS
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import ARDUPILOT_GAZEBO_PLUGIN, GAZEBO_LAYER
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER, RUNTIME_ASSETS_VOLUME

CONTAINER_ASSETS = "/runtime_assets"
GEOFENCE = Geofence(57.76, 16.68, 20000.0)
BASE_HOST_PORT = 15000
START_BOOT_S = 60.0  # scenario time 0 at this SITL time for every repeat, as in the Phase 2 measurements
TARGET_DISTANCE_M = 1500.0  # the Phase 0 driver sent one target this far east
GUIDED_WAIT_MS = 10_000  # SITL time allowed for the switch to GUIDED
TRACKS_SPEEDUP = 0.9  # a run tracked its request when it achieved at least this share of it
LAYERS = {"ardupilot_sim": SimulationLayerId.ARDUPILOT_SIM, "gazebo": SimulationLayerId.GAZEBO}
_LAYER_SPEC_ID = {SimulationLayerId.ARDUPILOT_SIM: ARDUPILOT_SIM_LAYER.id, SimulationLayerId.GAZEBO: GAZEBO_LAYER.id}
_PAIR_SPEC_ID = {SimulationLayerId.ARDUPILOT_SIM: SITL_INTERNAL_PHYSICS.id, SimulationLayerId.GAZEBO: ARDUPILOT_GAZEBO_PLUGIN.id}


@dataclass(frozen=True)
class StackRunSpec:
    simulation_layer: SimulationLayerId
    reference: str = "straight"  # one of REFERENCE_RUNS
    scale: str = "5m"
    duration_s: int = 90
    speedup: int = 1
    repeats: int = 3
    drive: str = "replay"  # replay or target
    wind: Optional[Tuple[float, float]] = None  # east, north in m/s

    def label(self) -> str:
        return f"{self.simulation_layer.value}-{self.drive}-{self.reference}-{self.scale}-{self.speedup}x"


@dataclass
class RepeatResult:
    index: int
    track: Optional[TrackSamples] = None
    achieved_speedup: Optional[float] = None
    state_digest: Optional[str] = None
    wall_s: float = 0.0
    error: Optional[str] = None
    logs: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and self.track is not None


@dataclass
class StackMeasurement:
    spec: StackRunSpec
    repeats: List[RepeatResult] = field(default_factory=list)
    deviation: Optional[DeviationSummary] = None

    @property
    def ok_repeats(self) -> List[RepeatResult]:
        return [repeat for repeat in self.repeats if repeat.ok]

    @property
    def achieved(self) -> Optional[float]:
        values = [repeat.achieved_speedup for repeat in self.ok_repeats if repeat.achieved_speedup]
        return float(min(values)) if values else None

    @property
    def tracks_request(self) -> bool:
        return self.achieved is not None and self.achieved >= TRACKS_SPEEDUP * self.spec.speedup

    def entries(self) -> List[MeasuredEntry]:
        """measured_capabilities.yaml entries for what this run measured (nothing when every repeat failed)."""
        if not self.ok_repeats:
            return []
        spec = self.spec
        layer = spec.simulation_layer
        note = evidence(
            f"{spec.drive} drive of a {spec.reference} {spec.scale} run ({spec.duration_s} s) on {layer.value} with the ardupilot control layer",
            requested=f"{spec.speedup}x",
            achieved=f"{self.achieved:.2f}x" if self.achieved else "unknown",
            repeats=len(self.ok_repeats),
            deviation_alignment=self.deviation.alignment if self.deviation else "none",
            max_deviation_m=f"{self.deviation.max_m:.3f}" if self.deviation else "n/a",
            identical_start=self.deviation.identical_prefix if self.deviation else "n/a",
        )
        entries: List[MeasuredEntry] = []
        if spec.drive == "replay":
            fields: Dict[str, Any] = {"evidence": note}
            if self.deviation:
                fields["deviation_bounds_m_by_layer"] = {_LAYER_SPEC_ID[layer]: {spec.speedup: self.deviation.max_m}}
            if layer == SimulationLayerId.ARDUPILOT_SIM and self.tracks_request:
                fields["max_speedup"] = float(spec.speedup)
            entries.append(MeasuredEntry(REPLAY_MAVLINK_LOCKSTEP.id, fields))
            if layer == SimulationLayerId.GAZEBO and self.tracks_request:
                entries.append(MeasuredEntry(_PAIR_SPEC_ID[layer], {"host_max_speedup": {host_label(): float(spec.speedup)}, "evidence": note}))
        else:
            fields = {"evidence": note}
            if self.deviation:
                fields["deviation_bounds_m"] = {spec.speedup: self.deviation.max_m}
            if layer == SimulationLayerId.GAZEBO and self.tracks_request:
                fields["host_max_speedup"] = {host_label(): float(spec.speedup)}
            elif layer == SimulationLayerId.ARDUPILOT_SIM and self.tracks_request:
                fields["max_speedup"] = float(spec.speedup)
            entries.append(MeasuredEntry(_PAIR_SPEC_ID[layer], fields))
        return entries


@contextmanager
def uncapped_generation() -> Iterator[StackResolver]:
    """A resolver without stored measurements, also used by the stack builder for the length of the block."""
    resolver = StackResolver(build_registry({}))
    with mock.patch("scenegems_tool.vessel_stack.simulation_docker_stack.default_resolver", lambda: resolver):
        yield resolver


def _rewrite(value: Any, replacements: Sequence[Tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_rewrite(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite(item, replacements) for key, item in value.items()}
    return value


def host_assets_replacements() -> List[Tuple[str, str]]:
    """Every spelling of the runtime assets folder that the generators write into files, mapped to the in-container mount."""
    spellings = [RUNTIME_ASSETS_FOLDER, RUNTIME_ASSETS_FOLDER.replace("\\", "/"), os.path.normpath(RUNTIME_ASSETS_FOLDER)]
    return [(old, CONTAINER_ASSETS) for old in sorted(set(spellings), key=len, reverse=True)]


def prepare_run_folder(
    spec: StackRunSpec,
    trajectories: Trajectories,
    folder: str,
    host_port: int,
    repo_entrypoints: bool = False,
) -> Tuple[str, Dict[str, str], Any]:
    """Generate the stack of one repeat under `folder`. Returns the compose file, the endpoint by agent id and the instance."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig

    environment = EnvironmentConfig.calm()
    if spec.wind is not None:
        environment.wind_vector = np.array([spec.wind[0], spec.wind[1], 0.0])
    instance = mavlink_replay_instance(trajectories, spec.simulation_layer, environment=environment, speedup=spec.speedup)
    connection = MQttConnectionInfo(user="", password="", agent_broker="broker", client_broker="broker", port=1883, tls_connection=False, allow_certificates=False)
    pending_writes, compose = build_simulation_docker_stack_artifacts(instance, trajectories, connection, GEOFENCE, embedded_in_subsystem=True)

    replacements = host_assets_replacements()
    assets = os.path.join(folder, "runtime_assets")
    for path, content in pending_writes:
        relative = os.path.relpath(os.path.normpath(path), os.path.normpath(RUNTIME_ASSETS_FOLDER))
        target = os.path.join(assets, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as file:
            file.write(_rewrite(content, replacements))

    compose = _rewrite(copy.deepcopy(compose), replacements)
    mount = f"{os.path.abspath(assets).replace(chr(92), '/')}:{CONTAINER_ASSETS}:ro"
    endpoints: Dict[str, str] = {}
    for index, (agent_id, vessel) in enumerate(instance.simulated_vessels.items()):
        service = compose["services"][vessel.require_connection().agent_name]
        port_in_container = 5760 + 10 * int(agent_id)
        service["ports"] = [f"127.0.0.1:{host_port + index}:{port_in_container}"]
        endpoints[agent_id] = f"tcp:127.0.0.1:{host_port + index}"
    for service in compose["services"].values():
        service["volumes"] = [mount if volume.startswith(f"{RUNTIME_ASSETS_VOLUME}:") else volume for volume in service.get("volumes", [])]
        service.pop("container_name", None)
        if "ports" in service and service is compose["services"].get("gazebo"):
            service.pop("ports")
        if repo_entrypoints:
            _mount_repo_entrypoint(service)
    compose.pop("volumes", None)
    compose_file = os.path.join(folder, "compose.yml")
    with open(compose_file, "w", encoding="utf-8", newline="\n") as file:
        yaml.dump(compose, file, default_flow_style=False, sort_keys=False, width=10000)
    return compose_file, endpoints, instance


def _mount_repo_entrypoint(service: Dict[str, Any]) -> None:
    """Mount the repo's entrypoint scripts over the image copies, for images built before the scripts changed."""
    from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH, GAZEBO_FOLDER, SITL_ENTRYPOINT_CONTAINER_PATH

    scripts = {"sitl": ("sitl_entrypoint.sh", SITL_ENTRYPOINT_CONTAINER_PATH), "gazebo": ("gazebo_entrypoint_prod.sh", GAZEBO_ENTRYPOINT_CONTAINER_PATH)}
    image = str(service.get("image", ""))
    key = "gazebo" if "GAZEBO_IMAGE" in image else "sitl" if "SITL_IMAGE" in image else None
    if key is None:
        return
    name, container_path = scripts[key]
    service["volumes"] = list(service.get("volumes", [])) + [f"{os.path.join(GAZEBO_FOLDER, name).replace(chr(92), '/')}:{container_path}:ro"]


class _Compose:
    def __init__(self, compose_file: str, project: str):
        self.base = ["docker", "compose", "-p", project, "-f", compose_file]

    def up(self) -> None:
        subprocess.run(self.base + ["down", "-v", "--remove-orphans"], capture_output=True)
        subprocess.run(self.base + ["up", "-d"], check=True, capture_output=True, text=True)

    def logs(self, tail: int = 40) -> str:
        return subprocess.run(self.base + ["logs", "--tail", str(tail)], capture_output=True, text=True).stdout

    def down(self) -> None:
        subprocess.run(self.base + ["down", "-v", "--remove-orphans"], capture_output=True)


def _drive_replay(trajectories: Trajectories, instance, endpoints: Dict[str, str], resolver: StackResolver) -> Tuple[TrackSamples, RepeatResult]:
    result: MavlinkRunResult = run_mavlink_replay(trajectories, instance, GEOFENCE, endpoints=endpoints, start_boot_s=START_BOOT_S, resolver=resolver)
    epoch = result.epoch_boot_ms[0]
    track = TrackSamples.from_stamped([sample for sample in result.samples[0] if sample.boot_ms >= epoch], epoch)  # the run itself, not the boot
    outcome = RepeatResult(index=-1, track=track, achieved_speedup=result.achieved_speedup, state_digest=result.state_digest(), wall_s=result.wall_s)
    return track, outcome


def _drive_target(spec: StackRunSpec, endpoint: str) -> RepeatResult:
    """Engage the vessel, send one position target far east, and sample it against SITL time for the run's duration.

    The track starts at the target: samples streamed while the vessel booted and armed are left out, and time is
    seconds of SITL time since the target was sent.
    """
    link = MavlinkLink(endpoint, 0, GEOFENCE)
    try:
        link.connect(600.0)
        link.wait_until_ready(600.0)
        link.engage(300.0)
        # GUIDED is refused until the estimator has settled (the replay path waits for the same SITL time).
        while (link.boot_ms or 0) < START_BOOT_S * 1000:
            link.poll(1.0)
        link.send_position_target((TARGET_DISTANCE_M, 0.0), link.boot_ms or 0)
        # The switch from HOLD to GUIDED clears the target of a vessel that has just entered the mode, so the
        # target is sent again once a heartbeat reports GUIDED.
        mode_deadline = (link.boot_ms or 0) + GUIDED_WAIT_MS
        while not link.in_guided and (link.boot_ms or 0) < mode_deadline:
            link.poll(1.0)
        start_boot = link.boot_ms or 0
        link.send_position_target((TARGET_DISTANCE_M, 0.0), start_boot)
        first_sample = len(link.samples)
        wall_start = time.monotonic()
        wall_deadline = wall_start + spec.duration_s / max(spec.speedup, 1) * 4 + 420
        while link.boot_ms is None or (link.boot_ms - start_boot) / 1000.0 < spec.duration_s:
            if time.monotonic() > wall_deadline:
                return RepeatResult(index=-1, error="the run did not reach its duration before the wall-clock timeout")
            link.poll(2.0)
        wall_span = time.monotonic() - wall_start
        track = TrackSamples.from_stamped(link.samples[first_sample:], start_boot)
        track = TrackSamples(track.time_s, track.x, track.y, track.speed, wall_span_s=wall_span)
        return RepeatResult(index=-1, track=track, achieved_speedup=achieved_speedup(track), wall_s=wall_span)
    finally:
        link.close()


def _validate(spec: StackRunSpec) -> None:
    if spec.reference not in REFERENCE_RUNS:
        raise ValueError(f"Unknown reference run '{spec.reference}'; expected one of {', '.join(REFERENCE_RUNS)}")
    if spec.drive not in ("replay", "target"):
        raise ValueError(f"Unknown drive '{spec.drive}'; expected replay or target")
    if spec.simulation_layer not in (SimulationLayerId.ARDUPILOT_SIM, SimulationLayerId.GAZEBO):
        raise ValueError(f"Docker measurements need ardupilot_sim or gazebo, got {spec.simulation_layer.value}")


def _run_repeat(spec: StackRunSpec, trajectories: Trajectories, prepared: Tuple[str, Dict[str, str], Any], index: int, resolver: StackResolver, keep_stacks: bool) -> RepeatResult:
    """Start one copy of the stack, drive it, and remove it. A failure is returned as data with the container logs."""
    compose_file, endpoints, instance = prepared
    compose = _Compose(compose_file, f"calib-{spec.label()}-{index}".lower().replace("_", "-"))
    try:
        compose.up()
        if spec.drive == "replay":
            _, outcome = _drive_replay(trajectories, instance, endpoints, resolver)
        else:
            outcome = _drive_target(spec, endpoint=endpoints["0"])
    except Exception as error:
        outcome = RepeatResult(index=index, error=f"{type(error).__name__}: {error}", logs=compose.logs())
    outcome.index = index
    if not keep_stacks:
        compose.down()
    return outcome


def measure_stack(
    spec: StackRunSpec,
    work_folder: str,
    base_host_port: int = BASE_HOST_PORT,
    repo_entrypoints: bool = False,
    keep_stacks: bool = False,
) -> StackMeasurement:
    """Start spec.repeats copies of the stack side by side, drive each, and compare the tracks.

    work_folder receives one folder per repeat with its generated files and compose file. Containers are removed
    afterwards unless keep_stacks is set. A repeat that fails is recorded with its error and the container logs.
    """
    _validate(spec)
    trajectories = reference_run(spec.reference, spec.scale, spec.duration_s)
    measurement = StackMeasurement(spec=spec)
    with uncapped_generation() as resolver:
        prepared = []
        for index in range(spec.repeats):
            folder = os.path.join(work_folder, f"{spec.label()}-{index}")
            os.makedirs(folder, exist_ok=True)
            prepared.append(prepare_run_folder(spec, trajectories, folder, base_host_port + 10 * index, repo_entrypoints))
        results: Dict[int, RepeatResult] = {}

        def run(index: int) -> None:
            results[index] = _run_repeat(spec, trajectories, prepared[index], index, resolver, keep_stacks)

        threads = [threading.Thread(target=run, args=(index,)) for index in range(spec.repeats)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    measurement.repeats = [results[index] for index in sorted(results)]
    tracks = [repeat.track for repeat in measurement.ok_repeats if repeat.track is not None]
    if len(tracks) >= 2:
        measurement.deviation = repeat_deviation(tracks, "scenario_time" if spec.drive == "replay" else "onset")
    return measurement
