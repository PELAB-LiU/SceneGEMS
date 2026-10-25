import pytest

from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NodeStore
from tests.scenegems_tool.persistence.stores.builders import CONFIG_HASH, ManualClock, make_class_spec


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def node_store(session_factory, clock) -> NodeStore:
    return NodeStore(session_factory, clock)


@pytest.fixture
def job_store(session_factory, clock) -> JobStore:
    return JobStore(session_factory, clock)


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


CLASS_A = "2vessel_0obstacle_scenarios/functional_model0"
CLASS_B = "3vessel_1obstacle_scenarios/functional_model5"


@pytest.fixture
def campaign(stores):
    """A campaign of two classes: A with quota 3 and failure budget 2, B with quota 2 and budget 1."""
    return stores.campaigns.create_campaign(
        "lab campaign",
        {"name": "lab campaign"},
        CONFIG_HASH,
        [make_class_spec(CLASS_A, quota=3, failure_budget=2), make_class_spec(CLASS_B, quota=2, failure_budget=1, vessels=3, obstacles=1)],
        pinned_fingerprints={"scenegems-scenario-execution": "fp-execution"},
    )
