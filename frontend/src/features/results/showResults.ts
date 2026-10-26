import { useUiStore } from "../../app/uiStore";
import { useResultsStore } from "../../domain/cluster/resultsStore";

/**
 * Opens the Results section on a campaign's verdicts. Other sections (Campaigns, P5.4) call this
 * from a "Show results" button: `showCampaignResults(campaign.campaign_id)`. It assumes the
 * campaign belongs to the selected cluster, which the section keeps for the whole session.
 */
export function showCampaignResults(campaignId: string): void {
  useResultsStore.getState().openCampaign(campaignId);
  useUiStore.getState().setSection("results");
}

/** Opens the Results section on one case of a campaign (its case page). */
export function showCaseResults(campaignId: string, caseId: number): void {
  useResultsStore.getState().openCase(campaignId, caseId);
  useUiStore.getState().setSection("results");
}
