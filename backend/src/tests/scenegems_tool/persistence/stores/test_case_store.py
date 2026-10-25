import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CampaignClassRow, CampaignClassState, CaseState, PipelineStage
from scenegems_tool.persistence.stores import CaseConflict, ClassCounts, ClassStateConflict, NewCase, UnknownCase, UnknownClass
from tests.scenegems_tool.persistence.stores.builders import sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B

pytestmark = pytest.mark.postgres


def _counts(stores, campaign_id, class_id):
    found = stores.cases.get_class(campaign_id, class_id)
    return ClassCounts(complete=found.complete_count, dropped=found.dropped_count, in_flight=found.in_flight_count)


def _create(stores, campaign, class_id=CLASS_A, indexes=(0,)):
    return stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=class_id, case_index=index, seed=1000 + index) for index in indexes])


def test_created_cases_are_active_and_counted_in_flight(stores, campaign):
    cases = _create(stores, campaign, indexes=(0, 1, 2))
    assert [(case.case_index, case.seed, case.stage, case.state, case.version) for case in cases] == [
        (0, 1000, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
        (1, 1001, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
        (2, 1002, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
    ]
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=3)
    assert _counts(stores, campaign.campaign_id, CLASS_B) == ClassCounts()
    assert stores.cases.get_case(cases[1].case_id) == cases[1]
    assert stores.cases.find_case(campaign.campaign_id, CLASS_A, 2) == cases[2]
    assert stores.cases.next_case_index(campaign.campaign_id, CLASS_A) == 3
    assert stores.cases.next_case_index(campaign.campaign_id, CLASS_B) == 0


def test_an_index_is_taken_once_per_class(stores, campaign):
    _create(stores, campaign, indexes=(0,))
    _create(stores, campaign, class_id=CLASS_B, indexes=(0,))
    with pytest.raises(IntegrityError):
        _create(stores, campaign, indexes=(0,))
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=1)


def test_cases_only_in_open_classes_of_the_campaign(stores, campaign):
    with pytest.raises(UnknownClass):
        _create(stores, campaign, class_id="6vessel_0obstacle_scenarios/functional_model1")
    stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.ABANDONED, reason="failure budget used up")
    with pytest.raises(ClassStateConflict):
        _create(stores, campaign, class_id=CLASS_B)


def test_moving_a_case_through_its_stages(stores, campaign, clock):
    (case,) = _create(stores, campaign)
    clock.advance(3)
    scene = sha256_of("scene")
    moved = stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.GENERATE_TRAJECTORIES, scene_artifact=scene, progress={"scene_job": "j1"})
    assert (moved.stage, moved.state, moved.version, moved.scene_artifact, moved.progress, moved.updated_at) == (
        PipelineStage.GENERATE_TRAJECTORIES,
        CaseState.ACTIVE,
        2,
        scene,
        {"scene_job": "j1"},
        clock.now,
    )
    trajectories = sha256_of("trajectories")
    moved = stores.cases.move_case(
        case.case_id, moved.version, stage=PipelineStage.SIMULATE, expected_stage=PipelineStage.GENERATE_TRAJECTORIES, trajectories_artifact=trajectories, trajectories_complete=True
    )
    assert (moved.stage, moved.trajectories_artifact, moved.trajectories_complete, moved.scene_artifact) == (PipelineStage.SIMULATE, trajectories, True, scene)
    done = stores.cases.move_case(case.case_id, moved.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    assert (done.state, done.finished_at) == (CaseState.COMPLETE, clock.now)
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(complete=1)


def test_a_stale_version_or_an_unexpected_stage_is_a_conflict(stores, campaign):
    (case,) = _create(stores, campaign)
    moved = stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.GENERATE_TRAJECTORIES)
    with pytest.raises(CaseConflict) as conflict:
        stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.SIMULATE)
    assert conflict.value.current == moved
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, moved.version, stage=PipelineStage.SIMULATE, expected_stage=PipelineStage.GENERATE_SCENE)
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, moved.version, state=CaseState.COMPLETE, expected_state=CaseState.DROPPED)
    assert stores.cases.get_case(case.case_id) == moved
    with pytest.raises(UnknownCase):
        stores.cases.move_case(10_000, 1)


def test_a_final_case_keeps_its_state_but_may_lose_its_artifacts(stores, campaign):
    (case,) = _create(stores, campaign)
    scene = sha256_of("scene")
    dropped = stores.cases.move_case(case.case_id, case.version, state=CaseState.DROPPED, scene_artifact=scene, reason="invalid scene")
    assert dropped.reason == "invalid scene"
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, dropped.version, state=CaseState.ACTIVE)
    cleared = stores.cases.move_case(case.case_id, dropped.version, scene_artifact=None)
    assert (cleared.state, cleared.scene_artifact, cleared.reason) == (CaseState.DROPPED, None, "invalid scene")


def test_artifacts_must_be_sha256_hex(stores, campaign):
    (case,) = _create(stores, campaign)
    with pytest.raises(ValueError):
        stores.cases.move_case(case.case_id, case.version, scene_artifact="ABC")


@pytest.mark.parametrize(
    "final, counts",
    [
        (CaseState.COMPLETE, ClassCounts(complete=1, in_flight=1)),
        (CaseState.DROPPED, ClassCounts(dropped=1, in_flight=1)),
        (CaseState.FAILED, ClassCounts(dropped=1, in_flight=1)),
        (CaseState.CANCELLED, ClassCounts(in_flight=1)),
    ],
)
def test_counts_follow_the_case_states(stores, campaign, final, counts):
    first, _ = _create(stores, campaign, indexes=(0, 1))
    stores.cases.move_case(first.case_id, first.version, state=final)
    assert _counts(stores, campaign.campaign_id, CLASS_A) == counts
    assert stores.cases.class_counts_from_cases(campaign.campaign_id)[CLASS_A] == counts


def test_failure_budget_left(stores, campaign):
    first, second = _create(stores, campaign, indexes=(0, 1))
    stores.cases.move_case(first.case_id, first.version, state=CaseState.DROPPED)
    stores.cases.move_case(second.case_id, second.version, state=CaseState.FAILED, reason="out of attempts: simulator crashed")
    assert stores.cases.get_class(campaign.campaign_id, CLASS_A).failure_budget_left == 0


def test_recount_repairs_counts_that_drifted(stores, campaign, session_factory):
    _create(stores, campaign, indexes=(0, 1))
    with transaction(session_factory) as session:
        session.execute(update(CampaignClassRow).where(CampaignClassRow.class_id == CLASS_A).values(in_flight_count=7, complete_count=1))
    (corrected,) = stores.cases.recount_classes(campaign.campaign_id)
    assert (corrected.class_id, corrected.in_flight_count, corrected.complete_count) == (CLASS_A, 2, 0)
    assert stores.cases.recount_classes(campaign.campaign_id) == []


def test_list_cases_by_class_and_state(stores, campaign):
    a0, a1, a2 = _create(stores, campaign, indexes=(0, 1, 2))
    (b0,) = _create(stores, campaign, class_id=CLASS_B, indexes=(0,))
    stores.cases.move_case(a1.case_id, a1.version, state=CaseState.COMPLETE)
    stores.cases.move_case(b0.case_id, b0.version, stage=PipelineStage.SIMULATE)
    listed = lambda **filters: [(case.class_id, case.case_index) for case in stores.cases.list_cases(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [(CLASS_A, 0), (CLASS_A, 1), (CLASS_A, 2), (CLASS_B, 0)]
    assert listed(class_id=CLASS_A, states=[CaseState.ACTIVE]) == [(CLASS_A, 0), (CLASS_A, 2)]
    assert listed(stages=[PipelineStage.SIMULATE]) == [(CLASS_B, 0)]
    assert listed(limit=2, offset=1) == [(CLASS_A, 1), (CLASS_A, 2)]
    assert stores.cases.count_cases(campaign.campaign_id) == 4
    assert stores.cases.count_cases(campaign.campaign_id, [CaseState.COMPLETE]) == 1


def test_class_states(stores, campaign, clock):
    clock.advance(9)
    closed = stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.COMPLETE, expected=CampaignClassState.OPEN)
    assert (closed.state, closed.finished_at) == (CampaignClassState.COMPLETE, clock.now)
    assert stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.COMPLETE) == closed
    with pytest.raises(ClassStateConflict):
        stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.ABANDONED)
    with pytest.raises(ClassStateConflict):
        stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.COMPLETE, expected=CampaignClassState.ABANDONED)
    assert [c.class_id for c in stores.cases.list_classes(campaign.campaign_id, [CampaignClassState.OPEN])] == [CLASS_B]


def test_several_moves_commit_together(stores, campaign):
    first, second = _create(stores, campaign, indexes=(0, 1))
    with pytest.raises(CaseConflict):
        with stores.transaction() as session:
            stores.cases.move_case(first.case_id, first.version, state=CaseState.COMPLETE, session=session)
            stores.cases.move_case(second.case_id, second.version + 1, state=CaseState.COMPLETE, session=session)
    assert stores.cases.get_case(first.case_id).state == CaseState.ACTIVE
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=2)
