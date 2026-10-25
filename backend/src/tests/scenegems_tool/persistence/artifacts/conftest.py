import pytest

from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.stores import ArtifactRecordStore
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def records(request, clock):
    """The artifact records in memory (default run) and in Postgres (`-m postgres`)."""
    if request.param == "memory":
        return InMemoryArtifactRecords(clock)
    return ArtifactRecordStore(request.getfixturevalue("session_factory"), clock)


@pytest.fixture
def artifacts(tmp_path, records) -> RecordedArtifacts:
    return RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records)
