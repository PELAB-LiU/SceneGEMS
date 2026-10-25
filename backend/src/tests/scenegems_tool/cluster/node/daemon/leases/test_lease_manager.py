"""The lease manager with a recording sender and a hand-driven clock; jobs are scripted (conftest.ScriptedJobs)."""

import threading
from typing import List

import pytest

from scenegems_tool.cluster.node.daemon.leases.lease import LeasePhase
from scenegems_tool.cluster.node.daemon.leases.lease_manager import LeaseManager
from scenegems_tool.cluster.node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import Cancel, Drain, JobResult, JobStatus, LeaseAccept, LeaseReject, LeaseRelease, LeaseRenew, LeaseRenewed, LogLines, Welcome
from tests.scenegems_tool.cluster.node.daemon.conftest import make_job, make_offer, wait_for

KINEMATIC = JobType.SIMULATION_KINEMATIC


class RecordingSender:
    def __init__(self) -> None:
        self.frames: List = []
        self.connected = True
        self._lock = threading.Lock()

    def send(self, frame) -> bool:
        if not self.connected:
            return False
        with self._lock:
            self.frames.append(frame)
        return True

    def of(self, kind) -> List:
        with self._lock:
            return [frame for frame in self.frames if isinstance(frame, kind)]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeNode:
    node_id = "n1"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def manager(sender, clock, jobs):
    manager = LeaseManager(SlotTable({KINEMATIC: 2}), FakeNode(), sender, run=jobs, clock=clock)
    manager.set_lease_timeout(9.0)
    yield manager
    manager.shutdown("test over", timeout_s=5.0)


def accept(manager, sender, jobs, lease_id: str):
    manager.on_offer(make_offer(lease_id, make_job(f"job-{lease_id}")))
    assert sender.of(LeaseAccept)[-1].lease_id == lease_id
    assert jobs.wait_started() == f"job-{lease_id}"


def test_an_accepted_lease_runs_and_reports_its_result(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    assert manager.running_lease_ids() == ["a"] and manager.slots_in_use() == {KINEMATIC: 1}
    jobs.finish("job-a", {"value": 1})
    wait_for(lambda: sender.of(JobResult))
    [result] = sender.of(JobResult)
    assert result.outcome == JobOutcome.SUCCEEDED and result.result == {"value": 1} and result.idempotency_key == "job-a/key"
    wait_for(lambda: not manager.busy)
    assert manager.slots_in_use() == {} and manager.running_lease_ids() == []
    kinds = [type(frame) for frame in sender.frames]
    assert kinds.index(JobStatus) < kinds.index(JobResult) and kinds.index(LogLines) < kinds.index(JobResult)


def test_offers_beyond_the_slots_and_unknown_types_are_rejected(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    accept(manager, sender, jobs, "b")
    manager.on_offer(make_offer("c"))
    manager.on_offer(make_offer("t", make_job("job-t", job_type=JobType.TRAJECTORY_GENERATION)))
    reasons = {frame.lease_id: frame.reason for frame in sender.of(LeaseReject)}
    assert reasons == {"c": "all 2 simulation.kinematic slots are in use", "t": "this node offers no trajectory_generation slots"}
    assert jobs.most_running == 2


def test_a_repeated_offer_of_a_held_lease_is_accepted_again_without_a_second_run(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.on_offer(make_offer("a", make_job("job-a")))
    assert [frame.lease_id for frame in sender.of(LeaseAccept)] == ["a", "a"]
    assert jobs.started.empty() and manager.slots_in_use() == {KINEMATIC: 1}


def test_an_accept_that_cannot_be_sent_runs_nothing(manager, sender, jobs):
    sender.connected = False
    manager.on_offer(make_offer("a"))
    assert not manager.busy and manager.slots_in_use() == {}
    assert jobs.started.empty()


def test_renewals_are_sent_every_third_of_the_timeout(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    clock.now += 2.9
    manager.tick()
    assert not sender.of(LeaseRenew)
    clock.now += 0.1
    manager.tick()
    manager.tick()
    assert [frame.lease_id for frame in sender.of(LeaseRenew)] == ["a"]
    clock.now += 3.0
    manager.tick()
    assert len(sender.of(LeaseRenew)) == 2


def test_confirmed_renewals_keep_the_lease_and_missing_ones_lose_it(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    for _ in range(5):
        clock.now += 3.0
        manager.tick()
        manager.handle(LeaseRenewed(lease_id="a", expires_at=make_offer("x").expires_at))
    assert manager.lease("a").phase == LeasePhase.RUNNING
    clock.now += 9.1
    manager.tick()
    wait_for(lambda: jobs.cancelled == ["job-a"])
    wait_for(lambda: not manager.busy)
    assert not sender.of(JobResult) and manager.slots_in_use() == {}


def test_renewals_wait_while_disconnected_and_go_out_on_reconnect(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    sender.connected = False
    clock.now += 4.0
    manager.tick()
    sender.connected = True
    manager.tick()
    assert len(sender.of(LeaseRenew)) == 1


def test_a_result_ready_while_disconnected_is_sent_by_the_ticker(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    sender.connected = False
    jobs.finish("job-a")
    wait_for(lambda: manager.lease("a").phase == LeasePhase.FINISHED)
    assert manager.running_lease_ids() == ["a"]  # still held: the next Hello names it
    assert manager.slots_in_use() == {}  # its containers are gone
    sender.connected = True
    manager.tick()
    assert len(sender.of(JobResult)) == 1
    assert not manager.busy


def test_cancel_stops_the_job_without_a_result(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.handle(Cancel(lease_id="a", job_id="job-a", reason="campaign stopped"))
    wait_for(lambda: not manager.busy)
    assert jobs.cancelled == ["job-a"] and not sender.of(JobResult)
    manager.handle(Cancel(lease_id="unknown", job_id="x", reason="late"))  # ignored


def test_drain_rejects_new_leases_and_running_ones_finish(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.handle(Drain(reason="update"))
    manager.on_offer(make_offer("b"))
    assert sender.of(LeaseReject)[-1].reason == "the node is draining (update)"
    jobs.finish("job-a")
    wait_for(lambda: sender.of(JobResult))


def test_shutdown_releases_running_leases_and_sends_finished_results(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    accept(manager, sender, jobs, "b")
    sender.connected = False
    jobs.finish("job-b")
    wait_for(lambda: manager.lease("b").phase == LeasePhase.FINISHED)
    sender.connected = True
    manager.shutdown("node stopping", timeout_s=5.0)
    assert [(frame.lease_id, frame.reason) for frame in sender.of(LeaseRelease)] == [("a", "node stopping")]
    assert [frame.lease_id for frame in sender.of(JobResult)] == ["b"]
    manager.on_offer(make_offer("c"))
    assert sender.of(LeaseReject)[-1].reason == "the node is shutting down"


def test_non_lease_messages_are_left_to_the_daemon(manager):
    assert not manager.handle(Welcome(master_id="m", heartbeat_interval_s=1.0, lease_timeout_s=3.0))
