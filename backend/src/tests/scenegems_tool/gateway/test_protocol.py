"""Wire messages shared with the frontend: builders, and the simulation-models body to the typed configuration and back."""

import copy

import numpy as np
import pytest

from scenegems_tool.gateway.protocol import (
    SimulationStatus,
    make_error_message,
    make_generated_scene_message,
    make_initial_state_message,
    make_monitor_status_message,
    make_preview_chunk_message,
    make_simulation_chunk_message,
    make_simulation_models_body,
    make_simulation_models_message,
    make_simulation_status_message,
    make_trajectory_generation_preview_message,
    make_trajectory_generation_result_message,
    make_waraps_status_message,
    simulation_config_from_body,
)
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext

BODY = {
    "simulatorType": "ArduPilot Sim",
    "windVector": [0.0, 0.0, 0.0],
    "wave": {"amplitude": 0.0, "period": 0.0, "steepness": 0.0, "direction": [0.0, 0.0]},
    "simulationSpeed": 2,
    "connectionsByAgentId": {
        "0": {"context": "simulation", "controlMode": "autonomous", "agentName": "os", "topic": "waraps/unit/surface/os", "port": 14550, "gazeboVesselModel": None},
        "1": {"context": "simulation", "controlMode": "external", "agentName": "ts", "topic": "waraps/unit/surface/ts", "port": 14560},
        "2": {"context": "real", "controlMode": "external", "agentName": "real", "topic": "waraps/unit/surface/real", "port": None},
    },
}


@pytest.fixture
def body():
    return copy.deepcopy(BODY)


class TestMessageBuilders:
    def test_simulation_status_values_are_the_wire_strings(self):
        assert {status.name: status.value for status in SimulationStatus} == {
            "NOT_INITIALIZED": "not initialized",
            "INITIALIZING": "initializing",
            "AGENTS_ARE_PREPARING": "agents are preparing",
            "READY_TO_START": "ready to start",
            "STARTING": "starting",
            "RUNNING": "running",
        }

    def test_simulation_status_message(self):
        assert make_simulation_status_message(SimulationStatus.RUNNING) == {"type": "simulation_status", "status": "running"}

    def test_waraps_and_monitor_status_messages(self):
        assert make_waraps_status_message(status="connected") == {"type": "waraps_status", "status": "connected"}
        assert make_monitor_status_message(status="disconnected") == {"type": "monitor_status", "status": "disconnected"}

    def test_error_message_carries_the_text(self, capsys):
        assert make_error_message("boom") == {"type": "error", "message": "boom"}
        assert "Error message: boom" in capsys.readouterr().out

    def test_error_message_survives_a_console_that_cannot_print_it(self, monkeypatch):
        printed = []

        def fussy_print(text):
            if any(ord(char) > 127 for char in text):
                raise UnicodeEncodeError("cp1252", text, 0, 1, "cannot encode")
            printed.append(text)

        monkeypatch.setattr("builtins.print", fussy_print)
        message = make_error_message("go → north")
        assert message["message"] == "go → north"
        assert printed == ["Error message: go ? north"]

    def test_initial_state_message_always_carries_the_scenario_id(self):
        assert make_initial_state_message("s1", 2, 100) == {"type": "initial_state", "scenarioId": "s1", "timeStep": 2, "trajectoryLength": 100}

    def test_generated_scene_message(self):
        assert make_generated_scene_message("r1", {"a": 1}, {"b": 2}, True) == {"type": "generated_scene", "requestId": "r1", "scene": {"a": 1}, "evaluationData": {"b": 2}, "valid": True}

    def test_trajectory_generation_messages(self):
        assert make_trajectory_generation_preview_message("r1", {"t": 1}) == {"type": "trajectory_generation_preview", "requestId": "r1", "trajectoryData": {"t": 1}}
        result = make_trajectory_generation_result_message("r1", None, 0, "failed")
        assert result == {"type": "trajectory_generation_result", "requestId": "r1", "trajectoryData": None, "valid": False, "errorMessage": "failed"}

    def test_chunk_messages(self):
        assert make_preview_chunk_message("s", 0, 9, [{"f": 1}]) == {"type": "preview_trajectory_chunk", "scenarioId": "s", "fromTimestamp": 0, "toTimestamp": 9, "frames": [{"f": 1}]}
        assert make_simulation_chunk_message("s", 10, 19, [])["type"] == "simulation_trajectory_chunk"


class TestSimulationConfigFromBody:
    def test_vessels_become_typed_configurations(self, body):
        config = simulation_config_from_body(body)
        assert config.simulation_layer == SimulationLayerId.ARDUPILOT_SIM
        assert config.speedup == 2
        assert set(config.vessels) == {"0", "1", "2"}
        first = config.vessels["0"]
        assert (first.stack.asv_software, first.stack.control_layer) == (AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT)
        assert first.connection.agent_name == "os" and first.connection.port == 14550
        assert first.adapter_ids == ("replay_arduagent_follower",)

    def test_external_vessels_use_the_default_adapter(self, body):
        assert simulation_config_from_body(body).vessels["1"].adapter_ids == ()

    def test_real_vessel_may_omit_its_port(self, body):
        real = simulation_config_from_body(body).vessels["2"]
        assert real.context == AgentContext.REAL
        assert real.connection.port is None
        assert not real.is_simulated

    def test_simulated_vessel_needs_a_port(self, body):
        body["connectionsByAgentId"]["1"]["port"] = None
        with pytest.raises(ValueError, match="Missing port for agent with context 'simulation'"):
            simulation_config_from_body(body)

    def test_unknown_context_is_rejected_with_the_choices(self, body):
        body["connectionsByAgentId"]["0"]["context"] = "hardware"
        with pytest.raises(ValueError, match="Unknown agent context 'hardware'; expected one of simulation, real"):
            simulation_config_from_body(body)

    def test_unknown_simulator_type_is_rejected(self, body):
        body["simulatorType"] = "Webots"
        with pytest.raises(ValueError, match="Unknown simulatorType 'Webots'"):
            simulation_config_from_body(body)

    def test_unknown_control_mode_is_rejected(self, body):
        body["connectionsByAgentId"]["0"]["controlMode"] = "manual"
        with pytest.raises(ValueError, match="Unknown controlMode 'manual'"):
            simulation_config_from_body(body)

    @pytest.mark.parametrize("wind", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], []])
    def test_wind_vector_needs_three_components(self, body, wind):
        body["windVector"] = wind
        with pytest.raises(ValueError, match="windVector must have 3 components"):
            simulation_config_from_body(body)

    def test_wind_and_wave_become_numpy_values(self, body):
        body["windVector"] = [1, 2, 0]
        body["wave"] = {"amplitude": 0.5, "period": 5, "steepness": 0.1, "direction": [1, 0]}
        environment = simulation_config_from_body(body).environment
        assert environment.wind_vector.dtype == float
        np.testing.assert_array_equal(environment.wind_vector, [1.0, 2.0, 0.0])
        assert environment.wave.amplitude == 0.5 and environment.waves_requested

    def test_speed_defaults_to_real_time(self, body):
        del body["simulationSpeed"]
        assert simulation_config_from_body(body).speedup == 1

    def test_a_provided_vessel_model_is_kept(self, body):
        body["connectionsByAgentId"]["0"]["gazeboVesselModel"] = "<sdf/>"
        assert simulation_config_from_body(body).vessels["0"].gazebo_vessel_model == "<sdf/>"


class TestRoundTrip:
    def test_body_to_config_and_back_keeps_the_wire_fields(self, body):
        config = simulation_config_from_body(body)
        again = make_simulation_models_body(config)
        assert again["simulatorType"] == "ArduPilot Sim"
        assert again["simulationSpeed"] == 2
        assert again["windVector"] == [0.0, 0.0, 0.0]
        for agent_id, connection in body["connectionsByAgentId"].items():
            sent = again["connectionsByAgentId"][agent_id]
            assert sent["context"] == connection["context"]
            assert sent["controlMode"] == connection["controlMode"]
            assert sent["agentName"] == connection["agentName"]
            assert sent["topic"] == connection["topic"]
            assert sent["port"] == connection["port"]

    def test_message_adds_the_type(self, body):
        message = make_simulation_models_message(simulation_config_from_body(body))
        assert message["type"] == "simulation_models"
        assert message["simulatorType"] == "ArduPilot Sim"

    def test_generated_vessel_model_is_sent_back(self, body):
        config = simulation_config_from_body(body)
        config.vessels["0"].gazebo_vessel_model = "<sdf/>"
        assert make_simulation_models_body(config)["connectionsByAgentId"]["0"]["gazeboVesselModel"] == "<sdf/>"

    def test_the_kinematic_layer_cannot_be_sent_to_the_browser_yet(self, body):
        config = simulation_config_from_body(body)
        config.simulation_layer = SimulationLayerId.KINEMATIC
        with pytest.raises(ValueError, match="no workbench simulatorType"):
            make_simulation_models_body(config)
