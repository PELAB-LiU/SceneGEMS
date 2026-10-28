"""TrajectoryData: the JSON round trip and the payload envelope."""

import json

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_data import MONITOR_FRAMES_KEY, TrajectoryData
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel


def _data(**changes):
    scenes = [ConcreteScene({make_vessel(0, True): ActorState(float(t), 0.0, 1.0, 0.0)}) for t in range(3)]
    fields = {"algorithm_desc": "rrt", "config_name": "c", "random_seed": 5, "max_iter": 10, "goal_sample_rate": 0.5, "timestamp": "t", "error_message": None, "trajectories": Trajectories(scenes, 2)}
    fields.update(changes)
    return TrajectoryData(**fields)


def test_save_and_load_round_trip(tmp_path):
    data = _data()
    file = tmp_path / "t.json"
    data.save_to_json(str(file))
    loaded = TrajectoryData.load_from_json(str(file))
    assert loaded.to_dict() == data.to_dict()
    assert loaded.trajectories.time_step == 2 and len(loaded.trajectories) == 3
    assert TrajectoryData.load_dict_from_json(str(file)) == json.loads(file.read_text())


def test_saving_prefers_the_stored_path(tmp_path):
    stored, other = tmp_path / "stored.json", tmp_path / "other.json"
    _data(path=str(stored)).save_to_json(str(other))
    assert stored.exists() and not other.exists()


def test_saving_needs_a_path():
    with pytest.raises(Exception, match="No path provided"):
        _data().save_to_json()


def test_from_payload_drops_the_monitor_frames_but_from_dict_stays_strict():
    payload = {**_data().to_dict(), MONITOR_FRAMES_KEY: [{"frame": 1}]}
    assert TrajectoryData.from_payload(payload).to_dict() == _data().to_dict()
    with pytest.raises(ValueError, match="monitor_frames"):
        TrajectoryData.from_dict(payload)


def test_the_string_form_lists_the_fields_sorted():
    text = str(_data(trajectories=None))
    assert text == repr(_data(trajectories=None))
    assert text.index("algorithm_desc") < text.index("random_seed")
