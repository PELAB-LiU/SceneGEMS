import { useEffect, useReducer, useState } from "react";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { CampaignSummary } from "../../domain/cluster/schemas";
import { SSH_TUNNEL_COMMAND } from "../cluster/ClusterListPanel";
import { formatDateTime, plural, runDuration } from "./campaignFormat";
import {
  ACTUAL_STATES,
  ACTUAL_STATE_LABELS,
  campaignProgress,
  INITIAL_LIST_VIEW,
  isFinalState,
  LIST_PAGE_SIZES,
  listViewReducer,
  pageInfo,
} from "./campaignModel";
import { EmptyState, ProgressBar, StateBadge } from "./campaignParts";
import { useCampaignDetails, useCampaignList } from "./useCampaignData";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export interface CampaignListProps {
  onOpen: (campaignId: string) => void;
  onCreate: () => void;
  clusterName: string;
  operatorUrl: string;
  /** The wizard has a half-filled campaign. */
  hasDraft: boolean;
}

function CampaignRow({
  campaign,
  progress,
  nowMs,
  onOpen,
}: {
  campaign: CampaignSummary;
  progress: ReturnType<typeof campaignProgress> | null;
  nowMs: number;
  onOpen: () => void;
}) {
  const finished = isFinalState(campaign.actual_state);
  return (
    <tr className="camp-row" onClick={onOpen}>
      <td className="camp-cell-name">
        <button type="button" className="camp-link" onClick={onOpen}>
          {campaign.name}
        </button>
        <code className="camp-id" title={campaign.campaign_id}>
          {campaign.campaign_id.slice(0, 8)}
        </code>
        {campaign.state_reason && <span className="camp-reason">{campaign.state_reason}</span>}
      </td>
      <td>
        <StateBadge state={campaign.actual_state} desired={campaign.desired_state} />
      </td>
      <td className="camp-cell-progress">
        {progress ? (
          progress.quota > 0 ? (
            <ProgressBar
              fraction={progress.fraction}
              tone={campaign.actual_state === "completed" ? "ok" : finished ? "idle" : "info"}
              label={
                <>
                  <strong>{progress.complete}</strong> of {progress.quota}
                  {progress.inFlight > 0 && <span className="camp-progress-sub">, {progress.inFlight} in flight</span>}
                  {progress.dropped > 0 && <span className="camp-progress-sub">, {progress.dropped} dropped</span>}
                </>
              }
            />
          ) : (
            <span className="meta">no quota</span>
          )
        ) : (
          <span className="meta">loading</span>
        )}
      </td>
      <td className="camp-cell-time">{formatDateTime(campaign.created_at)}</td>
      <td className="camp-cell-time">{campaign.finished_at ? formatDateTime(campaign.finished_at) : <span className="meta">not finished</span>}</td>
      <td className="camp-cell-duration">{runDuration(campaign.started_at, campaign.finished_at, nowMs)}</td>
    </tr>
  );
}

/** The selected cluster's campaigns: state, progress, times; filters by state and paging with totals. */
export function CampaignList({ onOpen, onCreate, clusterName, operatorUrl, hasDraft }: CampaignListProps) {
  const [view, dispatch] = useReducer(listViewReducer, INITIAL_LIST_VIEW);
  const list = useCampaignList(view);
  const campaigns = list.data?.items;
  const total = list.data?.total ?? null;
  const details = useCampaignDetails(campaigns ?? []);
  const now = useNow(1_000);

  useEffect(() => {
    if (total !== null) {
      dispatch({ type: "clampPage", total });
    }
  }, [total]);

  const error = list.error;
  const unreachable = error instanceof OperatorApiError && error.unreachable;

  if (list.isLoading) {
    return <p className="meta" role="status">Loading campaigns...</p>;
  }
  if (error && !list.data) {
    return (
      <EmptyState title={unreachable ? `Cannot reach ${clusterName}` : "The campaign list did not load"}>
        <p className="meta">{describeOperatorError(error)}</p>
        {unreachable && (
          <>
            <p className="meta">
              Check that the master runs and that its operator API is reachable at <code>{operatorUrl}</code>. For a remote master, open the tunnel first:
            </p>
            <code className="cluster-hint-command">{SSH_TUNNEL_COMMAND}</code>
          </>
        )}
        <div>
          <button type="button" onClick={() => void list.refetch()} disabled={list.isFetching}>
            {list.isFetching ? "Trying..." : "Try again"}
          </button>
        </div>
      </EmptyState>
    );
  }

  const shown = campaigns ?? [];
  const page = pageInfo(view, shown.length, total);
  const filtered = view.states.length > 0;

  return (
    <div className="camp-list">
      {hasDraft && (
        <div className="camp-draft-note" role="status">
          <span>A campaign you started in the wizard is waiting to be finished.</span>
          <button type="button" onClick={onCreate}>
            Continue the draft
          </button>
        </div>
      )}
      <div className="camp-filters" role="group" aria-label="Filter by state">
        <span className="camp-filters-label">State</span>
        <button type="button" className={`camp-chip${filtered ? "" : " camp-chip--on"}`} aria-pressed={!filtered} onClick={() => dispatch({ type: "clearStates" })}>
          All
        </button>
        {ACTUAL_STATES.map((state) => (
          <button
            key={state}
            type="button"
            className={`camp-chip${view.states.includes(state) ? " camp-chip--on" : ""}`}
            aria-pressed={view.states.includes(state)}
            onClick={() => dispatch({ type: "toggleState", state })}
          >
            {ACTUAL_STATE_LABELS[state]}
          </button>
        ))}
        {list.isFetching && !list.isLoading && <span className="meta camp-refreshing">updating</span>}
      </div>
      {error ? <p className="meta warning">The list may be stale: {describeOperatorError(error)}</p> : null}
      {shown.length === 0 ? (
        <EmptyState title={filtered ? "No campaign in these states" : "No campaigns yet"}>
          <p className="meta">
            {filtered
              ? "Clear the filter to see every campaign of this cluster."
              : "Create one in the wizard: choose the classes, the domain, the trajectory generator and the runs, then check the config on the master before it is created."}
          </p>
          <div>
            <button type="button" className="primary-btn accent" onClick={onCreate}>
              Create a campaign
            </button>
          </div>
        </EmptyState>
      ) : (
        <div className="camp-table-wrap">
          <table className="camp-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>State</th>
                <th>Progress (complete cases of quota)</th>
                <th>Created</th>
                <th>Finished</th>
                <th>Ran for</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((campaign) => {
                const detail = details.get(campaign.campaign_id);
                return (
                  <CampaignRow
                    key={campaign.campaign_id}
                    campaign={campaign}
                    progress={detail ? campaignProgress(detail.totals) : null}
                    nowMs={now}
                    onOpen={() => onOpen(campaign.campaign_id)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="camp-paging">
        <span className="meta">
          {page.total === 0 ? "No campaigns" : `${page.from} to ${page.to} of ${plural(page.total, "campaign")}`}
        </span>
        <span className="camp-paging-controls">
          <label className="camp-inline-field">
            Per page
            <select value={view.pageSize} onChange={(event) => dispatch({ type: "setPageSize", pageSize: Number(event.target.value) })}>
              {LIST_PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={!page.hasPrevious} onClick={() => dispatch({ type: "setPage", page: view.page - 1 })}>
            Previous
          </button>
          <span className="meta">
            Page {view.page + 1} of {page.pages}
          </span>
          <button type="button" disabled={!page.hasNext} onClick={() => dispatch({ type: "setPage", page: view.page + 1 })}>
            Next
          </button>
        </span>
      </div>
    </div>
  );
}
