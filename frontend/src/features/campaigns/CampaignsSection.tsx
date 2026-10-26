import "./campaigns.css";
import { usePersistedState } from "../../app/usePersistedState";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { CampaignDetail } from "./CampaignDetail";
import { CampaignList } from "./CampaignList";
import { EmptyState } from "./campaignParts";
import { CampaignWizard } from "./wizard/CampaignWizard";
import { useWizardStore } from "./wizard/wizardState";

type CampaignsView = { mode: "list" } | { mode: "detail"; campaignId: string } | { mode: "wizard" };

interface StoredView {
  clusterId: string | null;
  view: CampaignsView;
}

const LIST_VIEW: CampaignsView = { mode: "list" };

/** Whether the wizard holds something the operator entered. */
function useHasDraft(): boolean {
  return useWizardStore((state) => state.draft.name.trim() !== "" || state.visited.length > 0 || state.draft.scope.some((entry) => entry.classes.length > 0 || entry.patterns.length > 0));
}

/** The Campaigns section of the selected cluster: the list, one campaign's page, and the create wizard. */
export function CampaignsSection() {
  const cluster = useSelectedCluster();
  const [stored, setStored] = usePersistedState<StoredView>("campaigns-view", { clusterId: null, view: LIST_VIEW });
  const hasDraft = useHasDraft();
  // A page of another cluster's campaign is not shown for this one
  const view: CampaignsView = stored.clusterId === (cluster?.id ?? null) ? stored.view : LIST_VIEW;
  const show = (next: CampaignsView) => setStored({ clusterId: cluster?.id ?? null, view: next });

  let content;
  let actions;
  if (!cluster) {
    content = (
      <EmptyState title="No cluster selected">
        <p className="meta">Add a cluster or select one in the Cluster section to see its campaigns.</p>
      </EmptyState>
    );
  } else if (view.mode === "wizard") {
    content = <CampaignWizard key={cluster.id} onClose={() => show(LIST_VIEW)} onCreated={(campaignId) => show({ mode: "detail", campaignId })} />;
  } else if (view.mode === "detail") {
    content = <CampaignDetail key={`${cluster.id}/${view.campaignId}`} campaignId={view.campaignId} onBack={() => show(LIST_VIEW)} />;
  } else {
    content = (
      <CampaignList
        onOpen={(campaignId) => show({ mode: "detail", campaignId })}
        onCreate={() => show({ mode: "wizard" })}
        clusterName={cluster.name}
        operatorUrl={cluster.operatorUrl}
        hasDraft={hasDraft}
      />
    );
  }
  if (cluster && view.mode === "list") {
    actions = (
      <button type="button" className="primary-btn accent" onClick={() => show({ mode: "wizard" })}>
        {hasDraft ? "Continue the new campaign" : "New campaign"}
      </button>
    );
  }

  return (
    <SectionFrame title="Campaigns" subtitle="Create, follow and control the campaigns of the selected cluster." actions={actions}>
      {content}
    </SectionFrame>
  );
}
