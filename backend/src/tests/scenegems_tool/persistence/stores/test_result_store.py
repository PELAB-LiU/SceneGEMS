from dataclasses import replace

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CampaignClassState, CaseState, MonitorImplementation, PipelineStage, TrajectoryGeneratorImplementation, VerdictRow, VerdictState
from scenegems_tool.persistence.stores import NewCase, NewRunRecord, NewVerdict, UnknownCase
from tests.scenegems_tool.persistence.stores.builders import sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B

pytestmark = pytest.mark.postgres

STACK = {"own_ship": {"asv_software": "usv_navigation", "control_layer": "none", "simulation_layer": "kinematic"}}


def _cases(stores, campaign, class_id, count):
    return stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=class_id, case_index=index, seed=index) for index in range(count)])


def _run(case, run_index=0, repeat_index=0, digest="d" * 64):
    return NewRunRecord(
        case_id=case.case_id,
        run_index=run_index,
        repeat_index=repeat_index,
        trajectory_generator=TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT,
        trajectories_complete=True,
        stack=STACK,
        repeatability_tier="exact",
        environment={"wind_vector": None, "waves": None, "seed": 11},
        seed=11,
        dt=1.0,
        steps=600,
        state_digest=digest,
        artifacts={"trajectories": sha256_of("simulated")},
        job_id=None,
        node_id="node-a",
        fingerprints={"scenegems-scenario-execution": "fp-execution"},
        durations_s={"scene_generation": 2.5, "simulation": 0.4},
    )


def _verdict(case, state=VerdictState.PASSED, run_index=0, **fields):
    failed = state == VerdictState.FAILED
    defaults = dict(
        monitor=MonitorImplementation.EMPTY if state == VerdictState.UNMONITORED else MonitorImplementation.POST_HOC,
        rule_outcomes={"rule_16": {"passed": not failed, "first_failure_s": 61.0 if failed else None}},
        failed_rules=("rule_16",) if failed else (),
        first_failure_time_s=61.0 if failed else None,
    )
    defaults.update(fields)
    return NewVerdict(case_id=case.case_id, run_index=run_index, state=state, **defaults)


def test_a_run_record_holds_what_repeats_the_run(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    stored = stores.results.add_run_record(_run(case))
    assert (stored.campaign_id, stored.class_id, stored.case_id, stored.run_index, stored.repeat_index) == (campaign.campaign_id, CLASS_A, case.case_id, 0, 0)
    assert (stored.stack, stored.seed, stored.steps, stored.state_digest, stored.node_id) == (STACK, 11, 600, "d" * 64, "node-a")
    assert stored.trajectory_generator == TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT and stored.trajectories_complete
    assert stored.durations_s == {"scene_generation": 2.5, "simulation": 0.4}
    assert stores.results.get_run_record(stored.run_record_id) == stored


def test_a_run_record_is_written_once(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    first = stores.results.add_run_record(_run(case))
    assert stores.results.add_run_record(_run(case, digest="e" * 64)) == first
    second_repeat = stores.results.add_run_record(_run(case, repeat_index=1))
    assert second_repeat.run_record_id != first.run_record_id


def test_a_run_record_needs_a_case_and_hex_artifacts(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(UnknownCase):
        stores.results.add_run_record(replace(_run(case), case_id=99_999))
    with pytest.raises(ValueError):
        stores.results.add_run_record(replace(_run(case), artifacts={"trajectories": "not-a-hash"}))


def test_verdicts_by_state_class_and_case(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    run = stores.results.add_run_record(_run(a0))
    passed = stores.results.add_verdict(_verdict(a0, run_record_id=run.run_record_id))
    failed = stores.results.add_verdict(_verdict(a1, VerdictState.FAILED, sensitive=True))
    stores.results.add_verdict(_verdict(a2, VerdictState.PASSED))
    stores.results.add_verdict(_verdict(b0, VerdictState.UNMONITORED))
    assert (passed.run_record_id, passed.class_id, passed.failed_rules) == (run.run_record_id, CLASS_A, ())
    assert (failed.failed_rules, failed.first_failure_time_s, failed.sensitive) == (("rule_16",), 61.0, True)
    listed = lambda **filters: [verdict.case_id for verdict in stores.results.list_verdicts(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [a0.case_id, a1.case_id, a2.case_id, b0.case_id]
    assert listed(state=VerdictState.PASSED) == [a0.case_id, a2.case_id]
    assert listed(state=VerdictState.FAILED) == [a1.case_id]
    assert listed(class_id=CLASS_B) == [b0.case_id]
    assert listed(case_id=a2.case_id) == [a2.case_id]
    assert listed(sensitive=True) == [a1.case_id]
    assert listed(limit=1, offset=1) == [a1.case_id]
    assert stores.results.count_verdicts(campaign.campaign_id) == 4
    assert stores.results.count_verdicts(campaign.campaign_id, VerdictState.FAILED) == 1


def test_count_verdicts_takes_the_filters_of_list_verdicts(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    stores.results.add_verdict(_verdict(a0))
    stores.results.add_verdict(_verdict(a0, VerdictState.FAILED, run_index=1, sensitive=True))
    stores.results.add_verdict(_verdict(a1, VerdictState.FAILED))
    stores.results.add_verdict(_verdict(a2))
    stores.results.add_verdict(_verdict(b0, VerdictState.UNMONITORED))
    filters = [
        {},
        {"class_id": CLASS_A},
        {"class_id": CLASS_B},
        {"case_id": a0.case_id},
        {"state": VerdictState.FAILED},
        {"state": VerdictState.PASSED, "class_id": CLASS_A},
        {"run_index": 1},
        {"sensitive": True},
        {"sensitive": False, "state": VerdictState.FAILED},
    ]
    for keywords in filters:
        assert stores.results.count_verdicts(campaign.campaign_id, **keywords) == len(stores.results.list_verdicts(campaign.campaign_id, **keywords)), keywords
    assert stores.results.count_verdicts(campaign.campaign_id, run_index=0, class_id=CLASS_A) == 3
    assert stores.results.count_verdicts(campaign.campaign_id, state=VerdictState.FAILED, sensitive=True) == 1
    assert len(stores.results.list_verdicts(campaign.campaign_id, limit=1)) == 1 and stores.results.count_verdicts(campaign.campaign_id) == 5


def test_verdicts_and_run_records_carry_the_index_of_their_case(stores, campaign):
    cases = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (cases[2], b0, cases[0]):
        run = stores.results.add_run_record(_run(case))
        stored = stores.results.add_verdict(_verdict(case, run_record_id=run.run_record_id))
        assert stored.case_index == case.case_index
        assert run.case_index == case.case_index
    assert [(verdict.class_id, verdict.case_index) for verdict in stores.results.list_verdicts(campaign.campaign_id)] == [(CLASS_A, 0), (CLASS_A, 2), (CLASS_B, 0)]
    assert [record.case_index for record in stores.results.list_run_records(campaign.campaign_id)] == [0, 2, 0]
    found = stores.results.get_run_record(stores.results.list_run_records(campaign.campaign_id)[1].run_record_id)
    assert found.case_index == 2
    # storing the same verdict again returns the stored one, with its index
    assert stores.results.add_verdict(_verdict(cases[2])).case_index == 2


def test_one_verdict_per_case_and_run(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    first = stores.results.add_verdict(_verdict(case))
    assert stores.results.add_verdict(_verdict(case, VerdictState.FAILED)) == first
    assert stores.results.add_verdict(_verdict(case, run_index=1)).verdict_id != first.verdict_id


@pytest.mark.parametrize(
    "fields",
    [
        dict(state=VerdictState.UNMONITORED, monitor=MonitorImplementation.POST_HOC),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.EMPTY),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.POST_HOC, early_stop_time_s=40.0),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.LIVE, first_failure_time_s=3.0),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.POST_HOC, failed_rules=("rule_8",)),
    ],
)
def test_inconsistent_verdicts_are_refused(stores, campaign, fields):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(ValueError):
        stores.results.add_verdict(NewVerdict(case_id=case.case_id, run_index=0, **fields))


def test_the_table_refuses_what_the_store_checks(stores, campaign, session_factory):
    # The constraints hold also for writers that bypass the store's checks
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.execute(
                insert(VerdictRow).values(
                    case_id=case.case_id,
                    campaign_id=campaign.campaign_id,
                    class_id=CLASS_A,
                    run_index=0,
                    state="passed",
                    monitor="empty",
                    rule_outcomes={},
                    failed_rules=[],
                    sensitive=False,
                    created_at=case.created_at,
                )
            )


def test_a_live_verdict_with_an_early_stop(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    verdict = stores.results.add_verdict(_verdict(case, VerdictState.FAILED, monitor=MonitorImplementation.LIVE, early_stop_time_s=75.0))
    assert (verdict.monitor, verdict.early_stop_time_s, verdict.margin) == (MonitorImplementation.LIVE, 75.0, None)


def test_run_records_by_class_and_case(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (b0, a1, a0):
        stores.results.add_run_record(_run(case))
    stores.results.add_run_record(_run(a0, run_index=1))
    listed = lambda **filters: [(record.case_id, record.run_index) for record in stores.results.list_run_records(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [(a0.case_id, 0), (a0.case_id, 1), (a1.case_id, 0), (b0.case_id, 0)]
    assert listed(class_id=CLASS_B) == [(b0.case_id, 0)]
    assert listed(case_id=a0.case_id, run_index=1) == [(a0.case_id, 1)]
    assert listed(limit=2, offset=1) == [(a0.case_id, 1), (a1.case_id, 0)]


def test_count_run_records_takes_the_filters_of_list_run_records(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (b0, a1, a0):
        stores.results.add_run_record(_run(case))
    stores.results.add_run_record(_run(a0, run_index=1))
    stores.results.add_run_record(_run(a0, repeat_index=1))
    for keywords in ({}, {"class_id": CLASS_A}, {"class_id": CLASS_B}, {"case_id": a0.case_id}, {"run_index": 1}, {"case_id": a0.case_id, "run_index": 0}, {"class_id": CLASS_B, "run_index": 1}):
        assert stores.results.count_run_records(campaign.campaign_id, **keywords) == len(stores.results.list_run_records(campaign.campaign_id, **keywords)), keywords
    assert stores.results.count_run_records(campaign.campaign_id) == 5


def test_coverage_per_class(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case, state in ((a0, VerdictState.PASSED), (a1, VerdictState.FAILED)):
        stores.results.add_verdict(_verdict(case, state))
        stores.results.add_verdict(_verdict(case, VerdictState.UNMONITORED, run_index=1))
        current = stores.cases.get_case(case.case_id)
        stores.cases.move_case(case.case_id, current.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    stores.cases.move_case(a2.case_id, a2.version, state=CaseState.DROPPED, reason="invalid scene")
    stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.ABANDONED)
    coverage_a, coverage_b = stores.results.coverage(campaign.campaign_id)
    assert (coverage_a.class_id, coverage_a.state, coverage_a.quota, coverage_a.complete, coverage_a.dropped, coverage_a.in_flight) == (CLASS_A, CampaignClassState.OPEN, 3, 2, 1, 0)
    assert coverage_a.verdicts == {0: {VerdictState.PASSED: 1, VerdictState.FAILED: 1}, 1: {VerdictState.UNMONITORED: 2}}
    assert coverage_a.verdict_count(run_index=0) == 2 and coverage_a.verdict_count(VerdictState.FAILED) == 1
    assert (coverage_b.state, coverage_b.in_flight, coverage_b.verdicts, coverage_b.verdict_count()) == (CampaignClassState.ABANDONED, 1, {}, 0)
    assert b0.class_id == CLASS_B
