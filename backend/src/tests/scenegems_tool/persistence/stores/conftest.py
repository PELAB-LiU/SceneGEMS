import pytest

from scenegems_tool.persistence.stores import JobStore, NodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def node_store(session_factory, clock) -> NodeStore:
    return NodeStore(session_factory, clock)


@pytest.fixture
def job_store(session_factory, clock) -> JobStore:
    return JobStore(session_factory, clock)
