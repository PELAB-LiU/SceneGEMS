"""The exit campaign's 1050 cases on the fake fleet: the engine finishes them in reasonable time, with exact quotas."""

import time
from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign import load_campaign_config
from scenegems_tool.persistence.schema import CampaignActualState, CampaignClassState
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import create_campaign

pytestmark = [pytest.mark.postgres, pytest.mark.slow]

EXIT_CAMPAIGN = Path(__file__).resolve().parents[1] / "campaign" / "data" / "exit_campaign.yaml"
TIME_LIMIT_S = 1800.0


def test_the_exit_campaign_completes_its_1050_cases(make_harness):
    harness = make_harness(references=True)
    campaign = create_campaign(harness.stores, load_campaign_config(EXIT_CAMPAIGN).to_json())
    started = time.perf_counter()
    finished = harness.drive(campaign.campaign_id, rounds=5000)
    elapsed = time.perf_counter() - started
    assert finished.actual_state == CampaignActualState.COMPLETED
    states = assert_consistent(harness.stores, campaign.campaign_id)
    classes = harness.stores.cases.list_classes(campaign.campaign_id)
    assert len(classes) == 70 and all(record.state == CampaignClassState.COMPLETE for record in classes)
    assert states["complete"] == 1050 and harness.stores.results.count_verdicts(campaign.campaign_id) == 1050
    events = sum(report.events_read for report in harness.reports)
    jobs = len(harness.executor.reports)
    print(
        f"\nexit campaign: {sum(states.values())} cases ({states}), {jobs} jobs, {events} job events in {len(harness.reports)} ticks;"
        f" {elapsed:.1f} s in all, {harness.tick_seconds:.1f} s in engine ticks: {events / harness.tick_seconds:.0f} events/s,"
        f" {jobs / elapsed:.1f} jobs/s end to end"
    )
    assert elapsed < TIME_LIMIT_S
