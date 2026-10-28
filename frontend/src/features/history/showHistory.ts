import { useUiStore } from "../../app/uiStore";
import { useClusterStore } from "../../domain/cluster/clusterStore";
import { useHistoryStore } from "./historyStore";

/**
 * Opens Campaign History on one entry of the selected cluster (the Campaigns section calls this
 * after creating a campaign): `showHistoryEntry(campaign.campaign_id)`.
 */
export function showHistoryEntry(campaignId: string): void {
  useHistoryStore.getState().openEntry(useClusterStore.getState().selectedClusterId, campaignId);
  useUiStore.getState().setSection("history");
}

/** Opens Campaign History on its list. */
export function showHistoryList(): void {
  useHistoryStore.getState().closeEntry();
  useUiStore.getState().setSection("history");
}
