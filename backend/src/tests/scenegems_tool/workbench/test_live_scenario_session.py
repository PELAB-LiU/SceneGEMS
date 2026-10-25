"""LiveScenarioSession: a bare scene is a scenario of its initial scene only, a trajectory file loads as before."""

import json

import pytest

from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.subsystems.monitoring.empty_monitor_session import EmptyMonitorSession
from scenegems_tool.subsystems.trajectory_generation.straight_trajectory_generator import straight_trajectory_data
from scenegems_tool.workbench.empty_scenario_session import EmptyScenarioSession
from scenegems_tool.workbench.live_scenario_session import LiveScenarioSession
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def sent():
    return []


@pytest.fixture
async def monitor(sent):
    monitor = EmptyMonitorSession(sent.append)
    yield monitor
    monitor.destroy()


def bare_scene_file() -> str:
    return json.dumps(EvaluationData(best_scene=encounter_scene("head_on"), timeout=1, random_seed=3).to_dict())


def trajectory_file(timespan: int = 60, time_step: int = 15) -> str:
    return json.dumps(straight_trajectory_data(encounter_scene("head_on"), time_step, timespan, "head_on", 7).to_dict())


def load(content: str, monitor, sent) -> LiveScenarioSession:
    return LiveScenarioSession("s1", "scene.json", "dir/scene.json", content, monitor, sent.append)


def chunks(sent, kind: str = "preview_trajectory_chunk"):
    return [message for message in sent if message["type"] == kind]


class TestBareScene:
    async def test_it_holds_the_initial_scene_and_nothing_else(self, monitor, sent):
        session = load(bare_scene_file(), monitor, sent)
        assert len(session.trajectories) == 1
        assert session.trajectory_length == 0
        assert session.is_initialized and not session.has_trajectories

    async def test_no_trajectory_is_invented(self, monitor, sent, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("a bare scene must not get default trajectories")

        monkeypatch.setattr(TrajectoryBuilder, "default_builder_from_scene", staticmethod(refuse))
        monkeypatch.setattr(TrajectoryBuilder, "default_trajectory_from_scene", staticmethod(refuse))
        monkeypatch.setattr(TrajectoryBuilder, "simulate_to_timespan", refuse)
        session = load(bare_scene_file(), monitor, sent)
        assert not session.has_trajectories

    async def test_the_initial_state_message_reports_no_trajectory_length(self, monitor, sent):
        load(bare_scene_file(), monitor, sent)
        assert sent[0] == {"type": "initial_state", "scenarioId": "s1", "timeStep": 1, "trajectoryLength": 0}

    async def test_the_scene_view_gets_the_initial_scene_as_one_frame(self, monitor, sent):
        load(bare_scene_file(), monitor, sent)
        await settle()
        (chunk,) = chunks(sent)
        assert (chunk["scenarioId"], chunk["fromTimestamp"], chunk["toTimestamp"]) == ("s1", 0, 0)
        assert len(chunk["frames"]) == 1

    async def test_the_initial_scene_sits_at_the_own_ship(self, monitor, sent):
        session = load(bare_scene_file(), monitor, sent)
        own_ship_state = session.trajectories.initial_scene.os_state
        assert (own_ship_state.x, own_ship_state.y) == (0.0, 0.0)

    async def test_the_empty_monitor_shows_the_state_without_rule_results(self, monitor, sent):
        load(bare_scene_file(), monitor, sent)
        await settle()
        (frame,) = chunks(sent)[0]["frames"]
        assert frame["statesByActorId"]
        assert frame["ruleResults"] == frame["colregsStates"] == frame["situationContexts"] == frame["maneuverStates"] == []


class TestTrajectoryFile:
    async def test_the_whole_trajectory_is_loaded(self, monitor, sent):
        session = load(trajectory_file(timespan=60), monitor, sent)
        assert session.has_trajectories and session.is_initialized
        assert session.time_step == 1
        assert session.trajectory_length >= 60
        assert sent[0]["trajectoryLength"] == session.trajectory_length

    async def test_every_scene_reaches_the_preview_through_the_monitor(self, monitor, sent):
        session = load(trajectory_file(timespan=60), monitor, sent)
        await settle()
        frames = [frame for chunk in chunks(sent) for frame in chunk["frames"]]
        assert len(frames) == len(session.trajectories)


class TestEmptyScenarioSession:
    async def test_it_has_no_scenario_and_no_trajectories(self, monitor, sent):
        session = EmptyScenarioSession(monitor, sent.append)
        assert not session.is_initialized and not session.has_trajectories
