import { useEffect, useRef } from "react";
import "./results.css";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import type { CampaignSummary } from "../../domain/cluster/schemas";
import { CasePage } from "./CasePage";
import { formatTime } from "./resultsFormat";
import { useCampaignList } from "./useResultsData";
import { VerdictBrowser } from "./VerdictBrowser";

const STATE_TONE: Partial<Record<CampaignSummary["actual_state"], string>> = {
  running: "ok",
  completed: "ok",
  stalled: "bad",
  draining: "warn",
  paused: "warn",
};

function campaignOption(campaign: CampaignSummary): string {
  return `${campaign.name} (${campaign.actual_state}, ${formatTime(campaign.created_at).slice(0, 16)})`;
}

function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="section-empty" role="status">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

/** The Results section: a campaign's verdicts with filters, totals and CSV, down to one case's recorded run. */
export function ResultsSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  const clusterId = cluster?.id ?? null;
  const campaignId = useResultsStore((state) => state.campaignId);
  const caseId = useResultsStore((state) => state.caseId);
  const campaigns = useCampaignList(operatorUrl);

  // Another cluster has other campaigns: forget the one that was open (not on the first render).
  const shownCluster = useRef(clusterId);
  useEffect(() => {
    if (shownCluster.current !== clusterId) {
      shownCluster.current = clusterId;
      useResultsStore.getState().reset();
    }
  }, [clusterId]);

  const list = campaigns.data?.items ?? [];
  const effectiveId = campaignId ?? list[0]?.campaign_id ?? null;
  const selected = list.find((campaign) => campaign.campaign_id === effectiveId) ?? null;

  const picker = cluster && (
    <label className="results-picker">
      <span>Campaign</span>
      <select
        value={effectiveId ?? ""}
        onChange={(event) => useResultsStore.getState().openCampaign(event.target.value)}
        disabled={list.length === 0}
        aria-label="Campaign"
      >
        {effectiveId !== null && selected === null && <option value={effectiveId}>{effectiveId}</option>}
        {list.length === 0 && <option value="">{campaigns.isPending ? "Loading" : "No campaigns"}</option>}
        {list.map((campaign) => (
          <option key={campaign.campaign_id} value={campaign.campaign_id}>
            {campaignOption(campaign)}
          </option>
        ))}
      </select>
      {selected && <span className={`section-badge${STATE_TONE[selected.actual_state] ? ` section-badge--${STATE_TONE[selected.actual_state]}` : ""}`}>{selected.actual_state}</span>}
    </label>
  );

  let body: React.ReactNode;
  if (!cluster || operatorUrl === null) {
    body = (
      <EmptyState title="No cluster selected">
        <p className="meta">Select a cluster in the left pane to see the results of its campaigns.</p>
      </EmptyState>
    );
  } else if (campaigns.isError && effectiveId === null) {
    const unreachable = campaigns.error instanceof OperatorApiError && campaigns.error.unreachable;
    body = (
      <EmptyState title={unreachable ? "The master cannot be reached" : "The campaigns cannot be listed"}>
        <p className="meta">{describeOperatorError(campaigns.error)}</p>
        {unreachable && <p className="meta">The Cluster section shows how to open the SSH tunnel to the master&apos;s operator API.</p>}
        <button type="button" onClick={() => void campaigns.refetch()}>
          Try again
        </button>
      </EmptyState>
    );
  } else if (campaigns.isPending && effectiveId === null) {
    body = <p className="meta" role="status">Loading the campaigns.</p>;
  } else if (effectiveId === null) {
    body = (
      <EmptyState title="No campaign yet">
        <p className="meta">Create and start a campaign in the Campaigns section; its verdicts appear here as the cases finish.</p>
      </EmptyState>
    );
  } else if (caseId !== null) {
    body = (
      <CasePage key={`${effectiveId}:${caseId}`} operatorUrl={operatorUrl} campaignId={effectiveId} caseId={caseId} onBack={() => useResultsStore.getState().closeCase()} />
    );
  } else {
    body = <VerdictBrowser key={effectiveId} operatorUrl={operatorUrl} campaignId={effectiveId} />;
  }

  return (
    <SectionFrame title="Results" subtitle="Verdicts of a campaign, down to the recorded run of one case." actions={picker}>
      {body}
    </SectionFrame>
  );
}
