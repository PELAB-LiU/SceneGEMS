from dataclasses import replace

import pytest

from scenegems_tool.cluster.master.scheduling.node_eligibility import Ineligibility, ResourceGuard, ineligibility
from scenegems_tool.persistence.schema import NodeStatus
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello, make_resources

GUARD = ResourceGuard(min_free_memory_mb=512, max_load_average=1.5)


def _node(status=NodeStatus.ONLINE, free_memory_mb=8000, load_average=0.2):
    record = InMemoryNodeStore(ManualClock()).register(make_hello("node-a"))
    return replace(record, status=status, resources=make_resources(free_memory_mb=free_memory_mb).model_copy(update={"load_average": load_average}))


def test_an_online_up_to_date_node_with_room_is_eligible():
    assert ineligibility(_node(), out_of_date=False, fingerprints_known=True, guard=GUARD) is None


@pytest.mark.parametrize("status", [NodeStatus.DRAINING, NodeStatus.OFFLINE])
def test_only_online_nodes(status):
    assert ineligibility(_node(status=status), False, True, GUARD) == Ineligibility.NOT_ONLINE


def test_nothing_is_leased_while_the_expected_fingerprints_are_unknown():
    assert ineligibility(_node(), False, False, GUARD) == Ineligibility.FINGERPRINTS_UNKNOWN


def test_out_of_date():
    assert ineligibility(_node(), True, True, GUARD) == Ineligibility.OUT_OF_DATE


def test_resource_guard_bounds():
    assert ineligibility(_node(free_memory_mb=511), False, True, GUARD) == Ineligibility.LOW_MEMORY
    assert ineligibility(_node(free_memory_mb=512), False, True, GUARD) is None
    assert ineligibility(_node(load_average=1.51), False, True, GUARD) == Ineligibility.OVERLOADED
    assert ineligibility(_node(load_average=1.5), False, True, GUARD) is None
