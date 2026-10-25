import asyncio

import pytest

from scenegems_tool.cluster.master import server
from scenegems_tool.cluster.master.master_artifacts import MasterArtifacts
from scenegems_tool.cluster.master.settings import ArtifactSettings, MasterSettings
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def artifacts(tmp_path, clock):
    return RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), InMemoryArtifactRecords(clock))


def test_the_sweep_timer_deletes_unreferenced_artifacts_each_round(artifacts, clock, monkeypatch):
    stored = artifacts.put(b'{"old":true}', "scene", "application/json")
    clock.advance(120)
    master_artifacts = MasterArtifacts(artifacts, sweep_interval_s=0.01, sweep_grace_s=60)
    rounds = []
    sweep = artifacts.sweep
    monkeypatch.setattr(artifacts, "sweep", lambda grace_s: rounds.append(grace_s) or sweep(grace_s))

    async def run():
        master_artifacts.start_sweep()
        master_artifacts.start_sweep()  # once only
        while len(rounds) < 2:
            await asyncio.sleep(0.01)
        await master_artifacts.stop_sweep()
        await master_artifacts.stop_sweep()

    asyncio.run(run())
    assert rounds[:2] == [60, 60] and not artifacts.store.exists(stored.stored.sha256)


def test_a_failed_round_does_not_end_the_timer(artifacts, monkeypatch):
    master_artifacts = MasterArtifacts(artifacts, sweep_interval_s=0.01)
    calls = []

    def failing(grace_s):
        calls.append(grace_s)
        raise ConnectionError("database restarting")

    monkeypatch.setattr(artifacts, "sweep", failing)

    async def run():
        master_artifacts.start_sweep()
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        await master_artifacts.stop_sweep()

    asyncio.run(run())
    assert len(calls) >= 3


def test_an_interval_of_zero_turns_the_sweep_off(artifacts):
    master_artifacts = MasterArtifacts(artifacts, sweep_interval_s=0)

    async def run():
        master_artifacts.start_sweep()
        assert master_artifacts._task is None
        await master_artifacts.stop_sweep()

    asyncio.run(run())


def test_the_server_builds_the_store_on_the_artifact_folder(tmp_path):
    settings = MasterSettings(security_dir=tmp_path, database_url="postgresql+psycopg://x@localhost/x", broker_hook_secret="s", artifacts=ArtifactSettings(tmp_path / "artifacts", 1000, 30, 90))
    built = server.build_artifacts(settings, sessions=None)
    assert isinstance(built.artifacts.store, FileArtifactStore) and built.artifacts.store.root == tmp_path / "artifacts"
    assert (built.max_bytes, built.sweep_interval_s, built.sweep_grace_s) == (1000, 30, 90)
    assert (tmp_path / "artifacts" / ".incoming").is_dir()


def test_the_node_api_runs_the_sweep_with_its_timers(plane, security, artifacts):
    from starlette.testclient import TestClient

    from scenegems_tool.cluster.master.api.master_apps import create_node_api_app

    for run_timers in (True, False):
        master_artifacts = MasterArtifacts(artifacts, sweep_interval_s=3600)
        with TestClient(create_node_api_app(plane, security, run_timers=run_timers, artifacts=master_artifacts)):
            assert (master_artifacts._task is not None) == run_timers
        assert master_artifacts._task is None
