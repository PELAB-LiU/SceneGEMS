import pytest

from scenegems_tool.cluster.master.scheduling.reject_backoff import RejectBackoff
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def backoff(clock):
    return RejectBackoff(clock=clock)


def test_holds_double_up_to_the_maximum(backoff):
    assert [backoff.hold_s(rejects) for rejects in range(1, 8)] == [30, 60, 120, 240, 480, 600, 600]


def test_a_rejected_job_is_held_back_from_that_node_only(backoff, clock):
    until = backoff.rejected("node-a", "job-1")
    assert (until - clock.now).total_seconds() == 30
    assert backoff.held_jobs("node-a") == ["job-1"]
    assert backoff.held_jobs("node-b") == []
    clock.advance(30)
    assert backoff.held_jobs("node-a") == []


def test_each_further_reject_holds_longer(backoff, clock):
    backoff.rejected("node-a", "job-1")
    clock.advance(31)
    until = backoff.rejected("node-a", "job-1")
    assert (until - clock.now).total_seconds() == 60


def test_the_count_starts_again_after_a_quiet_maximum_hold(backoff, clock):
    backoff.rejected("node-a", "job-1")
    clock.advance(30 + 601)
    backoff.rejected("node-a", "job-2")  # prunes on the way
    until = backoff.rejected("node-a", "job-1")
    assert (until - clock.now).total_seconds() == 30


def test_an_ended_job_is_forgotten(backoff):
    backoff.rejected("node-a", "job-1")
    backoff.rejected("node-b", "job-1")
    backoff.rejected("node-a", "job-2")
    backoff.job_ended("job-1")
    assert backoff.held_jobs("node-a") == ["job-2"] and backoff.held_jobs("node-b") == []
