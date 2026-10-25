"""Restarts: an engine replaced mid-campaign, crashes between the steps of a tick, two engines on one database.

Every test ends with the same books: no case lost or duplicated, the counts agree with the
cases, one job per pipeline job, and the campaign complete with its exact quota.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import func, select

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CampaignActualState, CampaignDesiredState, CampaignEventKind, JobRow, PipelineJobRow
from scenegems_tool.persistence.stores import AssuranceStores
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, CLASS_B, config_dict, create_campaign
from tests.scenegems_tool.assurance.pipeline.fake_executor import LEASE_S

pytestmark = pytest.mark.postgres


def _assert_one_job_per_pipeline_job(harness, campaign_id: str) -> None:
    with transaction(harness.stores.session_factory) as session:
        pipeline_jobs = session.execute(select(func.count()).select_from(PipelineJobRow).where(PipelineJobRow.campaign_id == campaign_id)).scalar_one()
        linked = session.execute(select(func.count(func.distinct(PipelineJobRow.job_id))).where(PipelineJobRow.campaign_id == campaign_id)).scalar_one()
        jobs = session.execute(select(func.count()).select_from(JobRow).where(JobRow.idempotency_key.like(f"campaign:{campaign_id}:%"))).scalar_one()
    assert pipeline_jobs == linked == jobs


def _assert_finished_with_quota(harness, campaign, quota_cases: int) -> None:
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    states = assert_consistent(harness.stores, campaign.campaign_id)
    assert states.get("complete") == quota_cases
    _assert_one_job_per_pipeline_job(harness, campaign.campaign_id)


def test_a_new_engine_continues_where_the_old_one_stopped(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=3, failure_budget=1))
    for _ in range(3):
        harness.settle()
        harness.executor.run(limit=3)
    harness.settle()
    harness.executor.claim_all(limit=2)  # two jobs are leased when the master goes down
    # The master is down for longer than a lease: the leases expire and the jobs return to the queue
    harness.clock.advance(LEASE_S + 1)
    assert len(harness.job_store.expire_leases()) == 2
    harness.engine = harness.new_engine()
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 6)
    assert [event.kind for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None)].count(CampaignEventKind.ENGINE_STARTED) == 2


def test_a_crash_inside_a_tick_loses_nothing(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()
    position = harness.stores.pipeline.read_cursor()

    def crash(*arguments, **options):
        raise RuntimeError("the master died before the commit")

    monkeypatch.setattr(harness.stores.pipeline, "advance_cursor", crash)
    with pytest.raises(RuntimeError):
        harness.tick()
    monkeypatch.undo()
    assert harness.stores.pipeline.read_cursor() == position  # the events of the crashed tick are still ahead
    harness.engine = harness.new_engine()
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 2)


def test_a_commit_that_went_through_unacknowledged_is_not_taken_for_another_engine(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0))
    harness.settle()
    harness.executor.run()
    original = AssuranceStores.transaction

    @contextmanager
    def lost_acknowledgment(stores):
        with original(stores) as session:
            yield session
        raise ConnectionError("the connection dropped after the commit")

    monkeypatch.setattr(AssuranceStores, "transaction", lost_acknowledgment)
    with pytest.raises(ConnectionError):
        harness.tick()
    monkeypatch.undo()
    assert not harness.tick().stopped
    harness.drive(campaign.campaign_id)
    assert not harness.engine.stopped
    _assert_finished_with_quota(harness, campaign, 1)


def test_intents_left_by_a_crash_before_their_submission_are_resubmitted(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))

    async def crash_before_submitting(submissions):
        return 0

    monkeypatch.setattr(harness.engine, "_submit_all", crash_before_submitting)
    harness.tick()
    assert len(harness.stores.pipeline.intents_without_job(campaign.campaign_id)) == 4 and harness.job_store.list_jobs() == []
    harness.engine = harness.new_engine()
    harness.tick()
    assert harness.stores.pipeline.intents_without_job(campaign.campaign_id) == [] and len(harness.job_store.list_jobs()) == 4
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)


def test_a_crash_between_submission_and_link_resubmits_the_same_jobs(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()  # the scene results arrive

    def crash_before_linking(*arguments):
        raise RuntimeError("the master died before linking")

    monkeypatch.setattr(harness.engine, "_link", crash_before_linking)
    with pytest.raises(RuntimeError):
        harness.tick()
    unlinked = harness.stores.pipeline.intents_without_job(campaign.campaign_id)
    assert len(unlinked) == 4
    submitted = {job.idempotency_key: job.job_id for job in harness.job_store.list_jobs(state=JobState.QUEUED)}
    assert set(submitted) == {intent.idempotency_key for intent in unlinked}
    harness.engine = harness.new_engine()
    harness.tick()
    assert harness.stores.pipeline.intents_without_job(campaign.campaign_id) == []
    assert {key: harness.stores.pipeline.get_by_key(key).job_id for key in submitted} == submitted  # the job store returned the jobs it had
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)


def test_jobs_left_running_for_ended_cases_are_cancelled_at_start(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()

    async def crash_before_cancelling(outbox):
        return 0

    monkeypatch.setattr(harness.engine, "_cancel_jobs", crash_before_cancelling)
    harness.stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.STOPPED)
    harness.tick()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING  # stopped once its jobs are cancelled
    assert len(harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id, [JobState.QUEUED])) == 4
    harness.engine = harness.new_engine()
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.STOPPED
    assert {harness.job_store.get(job_id).state for job_id in harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id)} == {JobState.CANCELLED}
    (started,) = [event for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None) if event.kind == CampaignEventKind.ENGINE_STARTED][1:]
    assert started.detail["orphaned_jobs"] == 4
    assert_consistent(harness.stores, campaign.campaign_id)


def test_a_second_engine_on_the_same_database_stops(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=1))
    harness.settle()
    harness.executor.run()
    second = harness.new_engine()
    harness.run(second.start())
    harness.settle()  # the first engine processes the results and moves the cursor on
    report = harness.tick(second)
    assert report.stopped and second.stopped
    assert harness.tick(second).stopped
    harness.drive(campaign.campaign_id)
    assert not harness.engine.stopped
    _assert_finished_with_quota(harness, campaign, 4)
