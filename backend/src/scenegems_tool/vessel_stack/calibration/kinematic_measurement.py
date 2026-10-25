"""Kinematic layer measurements: reproducibility across repeats and processes, and pace.

The kinematic layer and the in-process USV Navigation adapter are the stacks that can reach the
`exact` tier, so this measurement is a check: every repeat must give the same state digest,
and so must a fresh process under any PYTHONHASHSEED. The pace is how many simulated seconds
the layer covers per wall second; it is limited only by the CPU, and is reported as steps per
second (design doc 10.5: over 10,000x for replay, over 1,000x for USV Navigation).
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import scenegems_tool
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.calibration.measured_entry import MeasuredEntry, evidence
from scenegems_tool.vessel_stack.calibration.reference_scenarios import ENCOUNTER_TARGETS, encounter_trajectories
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import KinematicRunResult, run_kinematic_closed_loop, run_kinematic_replay

DEFAULT_HASH_SEEDS = ("0", "1", "4242", "random")
SOURCE_ROOT = Path(scenegems_tool.__file__).resolve().parents[1]

_MODES = {"replay": run_kinematic_replay, "usv_navigation": run_kinematic_closed_loop}
_SPEC_BY_MODE = {"replay": "kinematic_command_input", "usv_navigation": "usv_navigation_in_process"}


@dataclass
class KinematicMeasurement:
    mode: str  # replay or usv_navigation
    encounter: str
    steps: int
    dt: float
    repeats: int
    digests: List[str] = field(default_factory=list)  # one per in-process repeat
    process_digests: Dict[str, str] = field(default_factory=dict)  # by PYTHONHASHSEED
    steps_per_second: float = 0.0  # simulated steps of the whole scene per wall second, best repeat

    @property
    def reproducible(self) -> bool:
        """Every repeat and every process produced the same digest."""
        return len(set(self.digests) | set(self.process_digests.values())) == 1

    @property
    def speed_relative_to_real_time(self) -> float:
        return self.steps_per_second * self.dt

    def entry(self) -> MeasuredEntry:
        """The measured_capabilities.yaml entry of the adapter this mode exercises.

        Only a reproducible result claims the exact tier. A speed limit of .inf says the layer has none
        of its own, as the shipped entries do; the measured pace goes into the evidence.
        """
        fields = {
            "repeatability_tier": "exact" if self.reproducible else "bounded",
            "evidence": evidence(
                f"{self.mode} on the kinematic layer, {self.encounter} encounter, {self.steps} steps of {self.dt:g} s",
                repeats=self.repeats,
                hash_seeds=",".join(self.process_digests) or "none",
                steps_per_second=f"{self.steps_per_second:,.0f}",
                times_real_time=f"{self.speed_relative_to_real_time:,.0f}",
                digests="identical" if self.reproducible else "DIFFER",
            ),
        }
        if self.reproducible:
            fields["max_speedup"] = float("inf")
        return MeasuredEntry(_SPEC_BY_MODE[self.mode], fields)


def _run(mode: str, trajectories: Trajectories) -> KinematicRunResult:
    return _MODES[mode](trajectories)


def digest_in_fresh_process(mode: str, encounter: str, timespan: int, hash_seed: str) -> str:
    """State digest of the same run in a new interpreter with the given PYTHONHASHSEED."""
    script = (
        "from scenegems_tool.vessel_stack.calibration.reference_scenarios import encounter_trajectories;"
        "from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay;"
        f"run = {{'replay': run_kinematic_replay, 'usv_navigation': run_kinematic_closed_loop}}[{mode!r}];"
        f"print(run(encounter_trajectories({encounter!r}, {timespan})).state_digest())"
    )
    environment = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(SOURCE_ROOT))
    completed = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(f"PYTHONHASHSEED={hash_seed} run failed:\n{completed.stderr}")
    return completed.stdout.strip().splitlines()[-1]


def measure_kinematic(
    mode: str = "usv_navigation",
    encounter: str = "crossing_from_starboard",
    timespan: int = 600,
    repeats: int = 3,
    hash_seeds: Optional[Sequence[str]] = DEFAULT_HASH_SEEDS,
) -> KinematicMeasurement:
    """Repeat one kinematic run in process and in fresh processes, and time it.

    mode is replay (every vessel follows its trajectory) or usv_navigation (the own ship runs USV
    Navigation in closed loop). The default encounter is long enough for USV Navigation to avoid and resume.
    """
    if mode not in _MODES:
        raise ValueError(f"Unknown mode '{mode}'; expected one of {', '.join(_MODES)}")
    if encounter not in ENCOUNTER_TARGETS:
        raise ValueError(f"Unknown encounter '{encounter}'; expected one of {', '.join(ENCOUNTER_TARGETS)}")
    trajectories = encounter_trajectories(encounter, timespan)
    measurement = KinematicMeasurement(mode=mode, encounter=encounter, steps=timespan, dt=float(trajectories.time_step), repeats=repeats)
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        result = _run(mode, trajectories)
        best = min(best, time.perf_counter() - started)
        measurement.digests.append(result.state_digest())
    measurement.steps_per_second = result.steps / best if best > 0 else 0.0
    for hash_seed in hash_seeds or ():
        measurement.process_digests[hash_seed] = digest_in_fresh_process(mode, encounter, timespan, hash_seed)
    return measurement
