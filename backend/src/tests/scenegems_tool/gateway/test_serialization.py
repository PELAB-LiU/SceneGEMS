"""Serialization of frames and monitor results for the frontend."""

import json
import os

import numpy as np
import pytest

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from scenegems_tool.gateway.serialization import _safety_domain_payload, _to_json_safe, serialize_frame, serialize_monitored_frame
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories
from utils.colregs_approximations import COLREGSConstraints
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER
from utils.safety_domains import CircularSafetyDomain, EllipticalSafetyDomain, RectangularSafetyDomain


class TestJsonSafe:
    def test_numpy_scalars_become_python_numbers(self):
        value = _to_json_safe({"a": np.float64(1.5), "b": np.int64(2), "c": np.bool_(True)})
        assert value == {"a": 1.5, "b": 2, "c": True}
        assert type(value["a"]) is float and type(value["b"]) is int and type(value["c"]) is bool
        json.dumps(value)

    def test_containers_are_converted_recursively(self):
        value = _to_json_safe({"list": [np.float32(1.0), (np.int32(2),)], "set": {np.int8(3)}})
        assert value == {"list": [1.0, [2]], "set": [3]}

    def test_keys_become_strings(self):
        assert _to_json_safe({1: "a"}) == {"1": "a"}

    def test_plain_values_pass_through(self):
        assert _to_json_safe("text") == "text"
        assert _to_json_safe(None) is None


class TestSafetyDomainPayload:
    def test_circle(self):
        payload = _safety_domain_payload(CircularSafetyDomain(np.array([1.0, 2.0]), 0.5, 30.0))
        assert payload == {"center": [1.0, 2.0], "heading": 0.5, "shape": "circle", "radius": 30.0}

    def test_ellipse(self):
        payload = _safety_domain_payload(EllipticalSafetyDomain(np.array([0.0, 0.0]), 0.0, 40.0, 20.0))
        assert (payload["shape"], payload["a"], payload["b"]) == ("ellipse", 40.0, 20.0)

    def test_rectangle(self):
        payload = _safety_domain_payload(RectangularSafetyDomain(np.array([0.0, 0.0]), 0.0, 40.0, 20.0))
        assert (payload["shape"], payload["a"], payload["b"]) == ("rectangle", 40.0, 20.0)

    def test_payloads_are_json_serializable(self):
        json.dumps(_safety_domain_payload(CircularSafetyDomain(np.array([1.0, 2.0]), 0.5, 30.0)))


class TestFrame:
    @pytest.fixture(scope="module")
    def scene(self):
        return encounter_trajectories("head_on", 10).initial_scene

    def test_frame_has_the_fields_the_frontend_reads(self, scene):
        frame = serialize_frame("s1", scene, 3, 1)
        assert (frame["scenarioId"], frame["timestamp"], frame["timeStep"]) == ("s1", 3, 1)
        assert set(frame) >= {"actors", "statesByActorId", "situationContexts", "colregsStates", "ruleResults", "maneuverStates", "metrics"}

    def test_actors_are_listed_with_their_dimensions_and_limits(self, scene):
        frame = serialize_frame("s1", scene, 0, 1)
        own = next(actor for actor in frame["actors"] if actor["isOwnShip"])
        assert own["id"] == "0"
        assert own["length"] == 30.0 and own["safetyRadius"] == 120.0
        assert own["maxSpeed"] == pytest.approx(20.57778)
        assert {"rudderMass", "propellerDiameter", "motorLength"} <= set(own)
        assert sum(actor["isOwnShip"] for actor in frame["actors"]) == 1

    def test_states_are_keyed_by_actor_id(self, scene):
        states = serialize_frame("s1", scene, 0, 1)["statesByActorId"]
        assert states["0"] == {"x": 0.0, "y": 0.0, "speed": 8.0, "heading": 0.0}
        assert states["1"]["x"] == 6000.0

    def test_frame_is_json_serializable(self, scene):
        json.dumps(serialize_frame("s1", scene, 0, 1))


class TestMonitoredFrame:
    @pytest.fixture(scope="module")
    def monitored(self):
        with open(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"), encoding="utf-8") as file:
            constants = COLREGSConstraints.from_file_content(file.read())
        trajectories = encounter_trajectories("head_on", 400)
        runtime = ColregsMonitorRuntime(constants)
        results = []
        for index, scene in enumerate(trajectories.scene_list):
            runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index, time_step=1))
            results.extend(runtime.monitor_current_tasks())
        return results

    def test_every_scene_is_monitored(self, monitored):
        assert len(monitored) == 401

    def test_frame_combines_the_scene_and_the_monitor_payload(self, monitored):
        frame = serialize_monitored_frame("s1", monitored[200], 200, 1)
        assert frame["timestamp"] == 200
        assert set(frame["statesByActorId"]) == {"0", "1"}
        assert frame["situationContexts"], "a head-on encounter at 200 s has a situation context"

    def test_frame_is_json_serializable(self, monitored):
        json.dumps(serialize_monitored_frame("s1", monitored[200], 200, 1))

    def test_serialization_is_deterministic(self, monitored):
        first = json.dumps(serialize_monitored_frame("s1", monitored[300], 300, 1), sort_keys=True)
        second = json.dumps(serialize_monitored_frame("s1", monitored[300], 300, 1), sort_keys=True)
        assert first == second
