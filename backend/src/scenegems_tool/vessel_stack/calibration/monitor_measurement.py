"""COLREGS monitor measurements: throughput, and whether its output is reproducible.

The monitor is the throughput limit of a kinematic campaign (design doc 10.5: about 1,100 to
1,300 scenes per second per core for two vessels, ten times slower than the kinematic layer).
Its output must also be reproducible, because the evidence of a verdict is hashed: the same
scenes must give the same serialized frames. Phase 0 found frames that were equal across repeats
in one process but not across processes, because rule lists follow set order (design doc 10.6,
item 2). This measurement checks both, so the fix can be verified by running it again.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import scenegems_tool
from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.serialization import serialize_monitored_frame
from scenegems_tool.vessel_stack.calibration.reference_scenarios import ENCOUNTER_TARGETS, encounter_trajectories
from utils.colregs_approximations import COLREGSConstraints
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER

DEFAULT_HASH_SEEDS = ("0", "1", "4242")
DEFAULT_CONSTANTS_FILE = "general_maritime_constants.yaml"
SOURCE_ROOT = Path(scenegems_tool.__file__).resolve().parents[1]


def load_constants(file_name: str = DEFAULT_CONSTANTS_FILE) -> COLREGSConstraints:
    with open(os.path.join(COLREGS_CONSTANTS_FOLDER, file_name), encoding="utf-8") as file:
        return COLREGSConstraints.from_file_content(file.read())


def monitor_scenes(scenes: Sequence[ConcreteScene], constants: COLREGSConstraints, time_step: int = 1) -> List[MonitoredSceneWithResults]:
    """Monitor the scenes in order with a fresh runtime, as the in-process path of a campaign does."""
    runtime = ColregsMonitorRuntime(constants)
    results: List[MonitoredSceneWithResults] = []
    for index, scene in enumerate(scenes):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index, time_step=time_step))
        results.extend(runtime.monitor_current_tasks())
    return results


def frames_digest(results: Sequence[MonitoredSceneWithResults], time_step: int = 1) -> str:
    """SHA-256 over the serialized frames, key order fixed, as the evidence of a monitor run."""
    digest = hashlib.sha256()
    for result in results:
        frame = serialize_monitored_frame("calibration", result, result.timestamp, time_step)
        digest.update(json.dumps(frame, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


@dataclass
class MonitorMeasurement:
    encounter: str
    scenes: int
    constants_file: str
    repeat_seconds: List[float] = field(default_factory=list)
    digests: List[str] = field(default_factory=list)  # one per in-process repeat
    process_digests: Dict[str, str] = field(default_factory=dict)  # by PYTHONHASHSEED

    @property
    def scenes_per_second(self) -> float:
        return self.scenes / min(self.repeat_seconds) if self.repeat_seconds and min(self.repeat_seconds) > 0 else 0.0

    @property
    def reproducible_in_process(self) -> bool:
        return len(set(self.digests)) == 1

    @property
    def reproducible_across_processes(self) -> Optional[bool]:
        """None when no other process was run."""
        if not self.process_digests:
            return None
        return len(set(self.process_digests.values()) | set(self.digests)) == 1

    def as_dict(self) -> dict:
        data = asdict(self)
        data.update(
            scenes_per_second=round(self.scenes_per_second, 1),
            reproducible_in_process=self.reproducible_in_process,
            reproducible_across_processes=self.reproducible_across_processes,
        )
        return data


def digest_in_fresh_process(encounter: str, timespan: int, constants_file: str, hash_seed: str) -> str:
    script = (
        "from scenegems_tool.vessel_stack.calibration.monitor_measurement import frames_digest, load_constants, monitor_scenes;"
        "from scenegems_tool.vessel_stack.calibration.reference_scenarios import encounter_trajectories;"
        f"scenes = encounter_trajectories({encounter!r}, {timespan}).scene_list;"
        f"print(frames_digest(monitor_scenes(scenes, load_constants({constants_file!r}))))"
    )
    environment = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(SOURCE_ROOT))
    completed = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=900)
    if completed.returncode != 0:
        raise RuntimeError(f"PYTHONHASHSEED={hash_seed} monitor run failed:\n{completed.stderr}")
    return completed.stdout.strip().splitlines()[-1]


def measure_monitor(
    encounter: str = "head_on",
    timespan: int = 600,
    repeats: int = 2,
    constants_file: str = DEFAULT_CONSTANTS_FILE,
    hash_seeds: Optional[Sequence[str]] = DEFAULT_HASH_SEEDS,
) -> MonitorMeasurement:
    """Monitor the scenes of one encounter repeatedly in process and in fresh processes, timing each pass."""
    if encounter not in ENCOUNTER_TARGETS:
        raise ValueError(f"Unknown encounter '{encounter}'; expected one of {', '.join(ENCOUNTER_TARGETS)}")
    scenes = encounter_trajectories(encounter, timespan).scene_list
    constants = load_constants(constants_file)
    measurement = MonitorMeasurement(encounter=encounter, scenes=len(scenes), constants_file=constants_file)
    for _ in range(repeats):
        started = time.perf_counter()
        results = monitor_scenes(scenes, constants)
        measurement.repeat_seconds.append(time.perf_counter() - started)
        measurement.digests.append(frames_digest(results))
    for hash_seed in hash_seeds or ():
        measurement.process_digests[hash_seed] = digest_in_fresh_process(encounter, timespan, constants_file, hash_seed)
    return measurement
