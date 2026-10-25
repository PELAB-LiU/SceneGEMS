"""SocketSession: the per-connection state of the workbench gateway, with empty (offline) subsystem sessions.

Ported from the old test_socket_session_status.py, which tested SocketSession.get_simulation_status of
scenegems_tool.backend_service.session. The session no longer polls a status: the simulation session
pushes `simulation_status` messages, so the checks are on the messages and on the session objects.
"""

import json
from types import SimpleNamespace

import pytest

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.gateway.socket_session import NO_TRAJECTORIES_MESSAGE, SocketSession
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.workbench.empty_subsystem_integration_session import EmptySubsystemIntegrationSession
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene, encounter_trajectories, stack_instance

pytestmark = pytest.mark.anyio


@pytest.fixture
async def session(websocket):
    session = SocketSession(websocket)
    yield session
    session.cancel()


def types_sent(websocket):
    return [payload["type"] for payload in websocket.sent]


class TestInitialState:
    async def test_starts_with_empty_offline_sessions(self, session):
        assert isinstance(session.subsystem_integration_session, EmptySubsystemIntegrationSession)
        assert not session.subsystem_integration_session.is_connected
        assert not session.scenario_session.is_initialized

    async def test_simulation_is_not_initialized_while_offline(self, session):
        assert session.subsystem_integration_session.simulation_session.status == SimulationStatus.NOT_INITIALIZED

    async def test_the_initial_simulation_status_is_the_first_message_sent(self, session, websocket):
        await settle()
        assert websocket.sent[0] == {"type": "simulation_status", "status": "not initialized"}

    async def test_connection_id_is_stable_and_names_the_socket(self, session, websocket):
        assert session.connection_id == str(id(websocket))

    async def test_created_at_is_a_utc_timestamp(self, session):
        assert session.created_at_utc.endswith("+00:00")


class TestSending:
    async def test_payloads_reach_the_socket_in_order(self, session, websocket):
        session.send_payload({"type": "first"})
        session.send_payload({"type": "second"})
        await settle()
        assert types_sent(websocket)[-2:] == ["first", "second"]

    async def test_runtime_errors_are_sent_as_error_messages(self, session, websocket):
        session.send_runtime_error("something failed")
        await settle()
        assert {"type": "error", "message": "something failed"} in websocket.sent

    async def test_status_and_chunk_messages_are_not_logged(self, session, capsys):
        for message_type in ("simulation_status", "monitor_status", "waraps_status", "preview_trajectory_chunk", "simulation_trajectory_chunk"):
            session.log_payload("outgoing", {"type": message_type})
        assert capsys.readouterr().out == ""

    async def test_other_messages_are_logged_with_direction_and_type(self, session, capsys):
        session.log_payload("incoming", {"type": "start_simulation"})
        assert f"[ws][incoming] session_id={session.connection_id} type=start_simulation" in capsys.readouterr().out


class TestOfflineBehaviour:
    async def test_disconnect_reports_disconnected_and_keeps_an_empty_session(self, session, websocket):
        session.disconnect_from_waraps()
        await settle()
        assert {"type": "waraps_status", "status": "disconnected"} in websocket.sent
        assert isinstance(session.subsystem_integration_session, EmptySubsystemIntegrationSession)

    async def test_initializing_the_monitor_while_offline_is_an_error(self, session, websocket):
        session.set_monitor_session("monitor", "topic", "scope", "constraints")
        await settle()
        assert {"type": "error", "message": "WARAPS is not connected"} in websocket.sent

    async def test_shutting_down_the_monitor_reports_it(self, session, websocket):
        session.shut_down_monitor()
        await settle()
        assert {"type": "monitor_status", "status": "disconnected"} in websocket.sent

    async def test_a_simulation_needs_a_loaded_scenario(self, session, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        await settle()
        assert [payload["message"] for payload in websocket.sent if payload["type"] == "error"] == ["No scenario loaded", "No scenario loaded"]

    async def test_monitoring_a_scene_rejects_malformed_json(self, session):
        with pytest.raises(ValueError):
            await session.monitor_scene("r1", "{not json")


class TestSimulationConfigValidation:
    @pytest.fixture
    async def loaded(self, session, monkeypatch):
        """A session whose scenario counts as loaded and whose simulation session records what it is given."""
        trajectories = encounter_trajectories("head_on", 20)
        session.scenario_session = SimpleNamespace(is_initialized=True, has_trajectories=True, trajectories=trajectories)
        calls = SimpleNamespace(initialized=[], models=[])
        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", lambda **kwargs: calls.initialized.append(kwargs))
        monkeypatch.setattr(session.subsystem_integration_session.simulation_session, "generate_vessel_models", lambda scene, config: calls.models.append((scene, config)))
        return calls

    async def test_an_accepted_configuration_starts_the_simulation_session(self, session, loaded, websocket):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.set_simulation_session(config)
        assert len(loaded.initialized) == 1
        assert loaded.initialized[0]["simulation_config"] is config
        await settle()
        assert not [payload for payload in websocket.sent if payload["type"] == "error"]

    async def test_a_rejected_configuration_sends_the_reason_and_starts_nothing(self, session, loaded, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert loaded.initialized == []
        (error,) = [payload["message"] for payload in websocket.sent if payload["type"] == "error"]
        assert error.startswith("Simulation configuration rejected: ")
        assert "Gazebo needs actuator commands" in error

    async def test_vessel_models_are_generated_for_the_initial_scene(self, session, loaded):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.generate_simulation_models(config)
        assert len(loaded.models) == 1
        assert loaded.models[0][1] is config
        assert loaded.models[0][0] is session.scenario_session.trajectories.initial_scene

    async def test_a_rejected_configuration_generates_no_models(self, session, loaded, websocket):
        session.generate_simulation_models(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert loaded.models == []
        assert any(payload["type"] == "error" and "rejected" in payload["message"] for payload in websocket.sent)

    async def test_a_scenario_without_an_initial_scene_is_reported(self, session, loaded, websocket):
        session.scenario_session = SimpleNamespace(is_initialized=True, trajectories=SimpleNamespace(initial_scene=None))
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], adapter_ids=["replay_arduagent_follower"]))
        await settle()
        assert {"type": "error", "message": "No initial scene found"} in websocket.sent

    async def test_warnings_are_printed_not_sent(self, session, loaded, websocket, capsys):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], speedup=3))
        await settle()
        assert "Simulation configuration warning:" in capsys.readouterr().out
        assert len(loaded.initialized) == 1


class TestScenarioWithoutTrajectories:
    """A bare scene loaded into the workbench has its initial scene only: the simulation is refused, never fed invented trajectories."""

    @pytest.fixture
    async def bare(self, session, websocket, monkeypatch):
        calls = SimpleNamespace(initialized=[], models=[])
        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", lambda **kwargs: calls.initialized.append(kwargs))
        content = json.dumps(EvaluationData(best_scene=encounter_scene("head_on"), timeout=1, random_seed=3).to_dict())
        session.set_scenario_session("s1", "scene.json", "scene.json", content)  # replaces the simulation session
        monkeypatch.setattr(session.subsystem_integration_session.simulation_session, "generate_vessel_models", lambda scene, config: calls.models.append((scene, config)))
        await settle()
        return calls

    def errors(self, websocket):
        return [payload["message"] for payload in websocket.sent if payload["type"] == "error"]

    async def test_the_scene_is_loaded_without_trajectories(self, session, bare):
        assert session.scenario_session.is_initialized
        assert not session.scenario_session.has_trajectories

    async def test_initializing_the_simulation_is_refused_with_the_reason(self, session, bare, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"]))
        await settle()
        assert bare.initialized == []
        assert self.errors(websocket) == [NO_TRAJECTORIES_MESSAGE]
        assert "generate trajectories first" in NO_TRAJECTORIES_MESSAGE and "monitor-driven RRT or straight" in NO_TRAJECTORIES_MESSAGE

    async def test_the_refusal_comes_before_the_configuration_is_judged(self, session, bare, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert self.errors(websocket) == [NO_TRAJECTORIES_MESSAGE]

    async def test_vessel_models_can_still_be_generated_from_the_initial_scene(self, session, bare, websocket):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.generate_simulation_models(config)
        await settle()
        assert [(scene, given) for scene, given in bare.models] == [(session.scenario_session.trajectories.initial_scene, config)]
        assert self.errors(websocket) == []

    async def test_loading_trajectories_afterwards_allows_the_simulation(self, session, bare, websocket):
        content = json.dumps(
            {"trajectories": encounter_trajectories("head_on", 30).to_dict(), "algorithm_desc": "straight"},
        )
        session.set_scenario_session("s2", "planned.json", "planned.json", content)
        await settle()
        assert session.scenario_session.has_trajectories
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"]))
        assert len(bare.initialized) == 1


class TestCancel:
    async def test_cancel_stops_the_background_tasks(self, websocket):
        session = SocketSession(websocket)
        session.cancel()
        await settle()
        assert session.outbound_task.cancelled()
        assert session.waraps_connection_task.cancelled()
