import pytest

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def memory_plane() -> ControlPlane:
    """A control plane on the in-memory stores, for routes that read no database."""
    clock = ManualClock()
    nodes = InMemoryNodeStore(clock)
    return ControlPlane("lab-master", nodes, InMemoryJobStore(nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
