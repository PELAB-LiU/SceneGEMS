"""Checks every campaign test ends with: counts agree with the cases, quotas are exact, nothing is left running."""

from collections import Counter
from typing import Dict

from scenegems_tool.assurance.pipeline.pipeline_queries import UNFINISHED_JOB_STATES
from scenegems_tool.persistence.schema import CampaignClassState, CaseState
from scenegems_tool.persistence.stores import AssuranceStores


def assert_consistent(stores: AssuranceStores, campaign_id: str, finished: bool = True) -> Dict[str, int]:
    """The campaign's books agree; returns the case count per state."""
    counted = stores.cases.class_counts_from_cases(campaign_id)
    classes = stores.cases.list_classes(campaign_id)
    for record in classes:
        counts = counted[record.class_id]
        assert (record.complete_count, record.dropped_count, record.in_flight_count) == (counts.complete, counts.dropped, counts.in_flight), record.class_id
    cases = stores.cases.list_cases(campaign_id)
    for class_id in {case.class_id for case in cases}:
        indexes = sorted(case.case_index for case in cases if case.class_id == class_id)
        assert indexes == list(range(len(indexes))), f"the cases of {class_id} are not a prefix of the indexes: {indexes}"
    coverage = {entry.class_id: entry for entry in stores.results.coverage(campaign_id)}
    config = stores.campaigns.config_version(campaign_id).config
    steps = config.get("steps", ["scene_generation", "trajectory_generation", "simulation"])  # format 1 runs the full chain
    runs = len(config["execution"]["runs"]) if "simulation" in steps else 0
    monitored = sum(
        1 for step, section in (("scene_generation", "scene_generation"), ("trajectory_generation", "trajectories")) if step in steps and config.get(section, {}).get("monitor") == "post_hoc"
    )
    for record in classes:
        if record.state == CampaignClassState.COMPLETE:
            assert record.complete_count == record.quota, record.class_id
            for run_index in range(runs):
                assert coverage[record.class_id].verdict_count(run_index=run_index) == record.quota, (record.class_id, run_index)
        assert record.complete_count <= record.quota
    verdict_cases = Counter(verdict.case_id for verdict in stores.results.list_verdicts(campaign_id, limit=None))
    complete = {case.case_id for case in cases if case.state == CaseState.COMPLETE}
    assert set(verdict_cases) == (complete if runs + monitored else set()), "verdicts belong to complete cases only, one per run and monitored generation step"
    assert all(count == runs + monitored for count in verdict_cases.values())
    if finished:
        assert stores.pipeline.job_ids_of_campaign(campaign_id, UNFINISHED_JOB_STATES) == []
        assert stores.pipeline.intents_without_job(campaign_id) == []
        assert all(case.state.is_final for case in cases)
    return dict(Counter(case.state.value for case in cases))
