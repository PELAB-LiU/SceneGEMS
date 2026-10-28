import "./campaigns.css";
import { EmptyState } from "../../components/EmptyState";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { showHistoryEntry, showHistoryList } from "../history/showHistory";
import { CampaignWizard } from "./wizard/CampaignWizard";

/**
 * The Campaigns section of the selected cluster: defining a campaign in the wizard and starting
 * it. Created campaigns open in Campaign History, where they are followed and controlled.
 */
export function CampaignsSection() {
  const cluster = useSelectedCluster();

  const actions = (
    <button type="button" onClick={showHistoryList} title="Follow, control and delete campaigns in Campaign History">
      Open Campaign History
    </button>
  );

  return (
    <SectionFrame title="Campaigns" subtitle="Define a campaign and start it. Follow it in Campaign History." actions={actions}>
      {cluster ? (
        <CampaignWizard key={cluster.id} onClose={showHistoryList} onCreated={showHistoryEntry} />
      ) : (
        <EmptyState title="No cluster selected">
          <p className="meta">Add a cluster or select one in the Cluster section to create campaigns on it.</p>
        </EmptyState>
      )}
    </SectionFrame>
  );
}
