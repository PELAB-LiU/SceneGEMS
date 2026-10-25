"""Kinematic digests are bit-identical across processes with different PYTHONHASHSEED values.

Set iteration order depends on the hash seed of the process, so a hidden dependence on it
(for example a set-ordered loop in the runtime or the monitor) shows up as a different
digest in a process with another seed. Each seed runs in its own subprocess, concurrently.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

import scenegems_tool
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

SOURCE_ROOT = Path(scenegems_tool.__file__).resolve().parents[1]
HASH_SEEDS = ("0", "1", "4242", "random")
ENCOUNTER = "crossing_from_starboard"
TIMESPAN = 600  # long enough for USV Navigation to avoid (229 s) and resume (548 s)

SCRIPT = f"""
import hashlib, json
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

trajectories = encounter_trajectories({ENCOUNTER!r}, {TIMESPAN})
replay = run_kinematic_replay(trajectories)
closed_loop = run_kinematic_closed_loop(trajectories)
record_hash = hashlib.sha256(json.dumps(closed_loop.run_record, sort_keys=True).encode("utf-8")).hexdigest()
print(json.dumps({{"replay": replay.state_digest(), "closed_loop": closed_loop.state_digest(), "closed_loop_record": record_hash}}))
"""


def run_in_subprocesses(hash_seeds) -> Dict[str, dict]:
    processes = {}
    for hash_seed in hash_seeds:
        environment = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(SOURCE_ROOT))
        processes[hash_seed] = subprocess.Popen([sys.executable, "-c", SCRIPT], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    results = {}
    for hash_seed, process in processes.items():
        stdout, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, f"PYTHONHASHSEED={hash_seed} failed:\n{stderr}"
        results[hash_seed] = json.loads(stdout.strip().splitlines()[-1])
    return results


@pytest.fixture(scope="module")
def subprocess_results() -> Dict[str, dict]:
    return run_in_subprocesses(HASH_SEEDS)


@pytest.fixture(scope="module")
def in_process():
    import hashlib

    trajectories = encounter_trajectories(ENCOUNTER, TIMESPAN)
    replay = run_kinematic_replay(trajectories)
    closed_loop = run_kinematic_closed_loop(trajectories)
    return {
        "replay": replay.state_digest(),
        "closed_loop": closed_loop.state_digest(),
        "closed_loop_record": hashlib.sha256(json.dumps(closed_loop.run_record, sort_keys=True).encode("utf-8")).hexdigest(),
        "closed_loop_result": closed_loop,
    }


def test_closed_loop_actually_avoids_so_the_digests_differ(in_process):
    assert in_process["replay"] != in_process["closed_loop"]
    assert in_process["closed_loop_result"].run_record["usv_navigation"]["transitions"]


def test_replay_digest_is_identical_across_hash_seeds(subprocess_results, in_process):
    digests: List[str] = [result["replay"] for result in subprocess_results.values()]
    assert set(digests) == {in_process["replay"]}


def test_usv_navigation_closed_loop_digest_is_identical_across_hash_seeds(subprocess_results, in_process):
    digests: List[str] = [result["closed_loop"] for result in subprocess_results.values()]
    assert set(digests) == {in_process["closed_loop"]}


def test_closed_loop_run_record_is_identical_across_hash_seeds(subprocess_results, in_process):
    records: List[str] = [result["closed_loop_record"] for result in subprocess_results.values()]
    assert set(records) == {in_process["closed_loop_record"]}
