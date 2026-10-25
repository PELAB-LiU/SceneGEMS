import pytest
from sqlalchemy.exc import IntegrityError

from scenegems_tool.persistence.schema import CampaignActualState, CampaignClassState, CampaignDesiredState, CampaignEventKind
from scenegems_tool.persistence.stores import CampaignStateConflict, ClassSpec, UnknownCampaign
from tests.scenegems_tool.persistence.stores.builders import CONFIG_HASH, START, make_class_spec, sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B

pytestmark = pytest.mark.postgres


def test_create_a_campaign_with_its_config_and_classes(stores, campaign):
    assert (campaign.name, campaign.desired_state, campaign.actual_state, campaign.config_version) == ("lab campaign", CampaignDesiredState.PAUSED, CampaignActualState.CREATED, 1)
    assert campaign.pinned_fingerprints == {"scenegems-scenario-execution": "fp-execution"}
    assert (campaign.created_at, campaign.started_at, campaign.finished_at) == (START, None, None)
    assert stores.campaigns.get_campaign(campaign.campaign_id) == campaign
    config = stores.campaigns.config_version(campaign.campaign_id)
    assert (config.version, config.config, config.config_hash) == (1, {"name": "lab campaign"}, CONFIG_HASH)
    assert stores.campaigns.config_versions(campaign.campaign_id) == [config]
    classes = stores.cases.list_classes(campaign.campaign_id)
    assert [(c.class_id, c.quota, c.failure_budget, c.vessel_count, c.obstacle_count, c.state) for c in classes] == [
        (CLASS_A, 3, 2, 2, 0, CampaignClassState.OPEN),
        (CLASS_B, 2, 1, 3, 1, CampaignClassState.OPEN),
    ]
    assert all((c.complete_count, c.dropped_count, c.in_flight_count) == (0, 0, 0) for c in classes)
    (created,) = stores.campaigns.list_events(campaign.campaign_id)
    assert created.kind == CampaignEventKind.CREATED and created.detail == {"config_hash": CONFIG_HASH, "classes": 2, "desired_state": "paused"}


def test_creation_is_one_transaction(stores):
    # The second class breaks a constraint, so neither the campaign nor its first class remain
    broken = ClassSpec(class_id=CLASS_B, content_hash=sha256_of(CLASS_B), vessel_count=2, obstacle_count=0, quota=0, failure_budget=0)
    with pytest.raises(IntegrityError):
        stores.campaigns.create_campaign("broken", {}, CONFIG_HASH, [make_class_spec(CLASS_A), broken])
    assert stores.campaigns.list_campaigns() == []


@pytest.mark.parametrize(
    "classes, hash_",
    [
        ([], CONFIG_HASH),
        ([make_class_spec(CLASS_A), make_class_spec(CLASS_A)], CONFIG_HASH),
        ([make_class_spec(CLASS_A)], "ABC"),
        ([ClassSpec(CLASS_A, "f" * 63, 2, 0, 1, 0)], CONFIG_HASH),
    ],
)
def test_creation_checks_its_input(stores, classes, hash_):
    with pytest.raises(ValueError):
        stores.campaigns.create_campaign("bad", {}, hash_, classes)


def test_list_campaigns_newest_first(stores, clock):
    first = stores.campaigns.create_campaign("first", {}, CONFIG_HASH, [make_class_spec()])
    clock.advance(1)
    second = stores.campaigns.create_campaign("second", {}, CONFIG_HASH, [make_class_spec()])
    assert [c.campaign_id for c in stores.campaigns.list_campaigns()] == [second.campaign_id, first.campaign_id]
    assert [c.campaign_id for c in stores.campaigns.list_campaigns(limit=1, offset=1)] == [first.campaign_id]
    stores.campaigns.set_actual_state(first.campaign_id, CampaignActualState.RUNNING)
    assert [c.name for c in stores.campaigns.list_campaigns([CampaignActualState.RUNNING])] == ["first"]
    assert [c.name for c in stores.campaigns.unfinished_campaigns()] == ["first", "second"]


def test_desired_state_changes_are_recorded(stores, campaign, clock):
    clock.advance(5)
    running = stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    assert running.desired_state == CampaignDesiredState.RUNNING and running.updated_at == clock.now
    # setting it again records nothing
    stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    events = stores.campaigns.list_events(campaign.campaign_id, kinds=[CampaignEventKind.DESIRED_STATE_CHANGED])
    assert [event.detail for event in events] == [{"from": "paused", "to": "running"}]


def test_desired_state_with_an_expectation(stores, campaign):
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING, expected=CampaignDesiredState.DRAINING)
    assert stores.campaigns.get_campaign(campaign.campaign_id).desired_state == CampaignDesiredState.PAUSED


def test_a_stop_is_final(stores, campaign):
    stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.STOPPED)
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.STOPPED)
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)


def test_actual_state_sets_start_and_finish_times(stores, campaign, clock):
    clock.advance(10)
    running = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)
    assert running.started_at == clock.now
    clock.advance(10)
    stalled = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.STALLED, reason="no node runs release 6de1e06")
    assert (stalled.state_reason, stalled.started_at) == ("no node runs release 6de1e06", running.started_at)
    clock.advance(10)
    resumed = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING, expected=CampaignActualState.STALLED)
    assert resumed.state_reason is None and resumed.started_at == running.started_at
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.PAUSED, expected=CampaignActualState.STALLED)
    done = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.COMPLETED)
    assert done.finished_at == clock.now


def test_events_in_order_with_paging(stores, campaign):
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.STARTED)
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.CLASS_COMPLETE, {"verdicts": 3}, class_id=CLASS_A)
    events = stores.campaigns.list_events(campaign.campaign_id)
    assert [event.kind for event in events] == [CampaignEventKind.CREATED, CampaignEventKind.STARTED, CampaignEventKind.CLASS_COMPLETE]
    assert (events[2].class_id, events[2].detail) == (CLASS_A, {"verdicts": 3})
    assert stores.campaigns.list_events(campaign.campaign_id, after_event_id=events[0].event_id, limit=1) == [events[1]]


def test_unknown_campaign(stores):
    assert stores.campaigns.get_campaign("missing") is None
    assert stores.campaigns.config_version("missing") is None
    with pytest.raises(UnknownCampaign):
        stores.campaigns.set_desired_state("missing", CampaignDesiredState.RUNNING)
    with pytest.raises(UnknownCampaign):
        stores.campaigns.append_event("missing", CampaignEventKind.NOTE)


def test_a_change_in_the_callers_transaction_rolls_back_with_it(stores, campaign):
    with pytest.raises(RuntimeError):
        with stores.transaction() as session:
            stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING, session=session)
            stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.NOTE, session=session)
            raise RuntimeError("engine step failed")
    assert stores.campaigns.get_campaign(campaign.campaign_id).desired_state == CampaignDesiredState.PAUSED
    assert len(stores.campaigns.list_events(campaign.campaign_id)) == 1
