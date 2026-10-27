import { useEffect, useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import type { CampaignDetail as CampaignDetailView } from "../../domain/cluster/schemas";
import { formatDateTime, plural, runDuration } from "./campaignFormat";
import { campaignProgress, runNames } from "./campaignModel";
import { EmptyState, ProgressBar, StateBadge, Tile } from "./campaignParts";
import { ConfigPanel } from "./ConfigPanel";
import { ControlsBar } from "./ControlsBar";
import { CoverageTable } from "./CoverageTable";
import { EventsFeed } from "./EventsFeed";
import { showCampaignResults } from "../results/showResults";
import { useCampaignConfig, useCampaignEvents, useCampaignFeed, useStartBlocker } from "./useCampaignData";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function Totals({ detail }: { detail: CampaignDetailView }) {
  const progress = campaignProgress(detail.totals);
  const { totals } = detail;
  const verdicts = totals.verdicts;
  const failed = verdicts.failed ?? 0;
  return (
    <>
      <div className="stat-tiles camp-tiles">
        <div className="stat-tile camp-tile-wide">
          <span className="stat-tile-label">Complete cases</span>
          <span className="stat-tile-value">
            {progress.complete} <span className="camp-tile-of">of {progress.quota}</span>
          </span>
          <ProgressBar fraction={progress.fraction} tone={detail.actual_state === "completed" ? "ok" : "info"} />
          <span className="stat-tile-detail">
            {progress.inFlight} in flight
            {progress.dropped > 0 ? `, ${progress.dropped} dropped (they count against the failure budgets)` : ""}
          </span>
        </div>
        <Tile
          label="Verdicts"
          value={Object.values(verdicts).reduce((sum, count) => sum + count, 0)}
          detail={`${verdicts.passed ?? 0} passed, ${failed} failed`}
          tone={failed > 0 ? "warn" : undefined}
        />
        {totals.classes_abandoned > 0 && (
          <Tile label="Abandoned classes" value={totals.classes_abandoned} detail="out of failure budget" tone="bad" />
        )}
      </div>
      <Disclosure id="campaign:more-numbers" variant="link" headingLevel={null} title="More numbers" openTitle="Fewer numbers">
        <div className="stat-tiles camp-tiles">
          <Tile label="In flight" value={progress.inFlight} detail="cases being worked on" />
          <Tile label="Dropped" value={progress.dropped} detail="count against the failure budgets" tone={progress.dropped > 0 ? "warn" : undefined} />
          <Tile
            label="Classes"
            value={totals.classes}
            detail={`${totals.classes_open} open, ${totals.classes_complete} complete, ${totals.classes_abandoned} abandoned`}
            tone={totals.classes_abandoned > 0 ? "bad" : undefined}
          />
          <Tile label="Unmonitored verdicts" value={verdicts.unmonitored ?? 0} detail="runs without a monitor result" />
        </div>
      </Disclosure>
    </>
  );
}

export interface CampaignDetailProps {
  campaignId: string;
  onBack: () => void;
}

/** One campaign: summary, controls, coverage per class kept live, the events feed, its config and the way to its results. */
export function CampaignDetail({ campaignId, onBack }: CampaignDetailProps) {
  const feed = useCampaignFeed(campaignId);
  const events = useCampaignEvents(campaignId, feed.lastEventId, feed.pushedEvents, feed.source === "poll");
  const config = useCampaignConfig(campaignId);
  const now = useNow(1_000);
  const { detail } = feed;
  const startBlocker = useStartBlocker(config.data);

  if (feed.loading) {
    return (
      <div className="camp-detail">
        <button type="button" className="camp-back" onClick={onBack}>
          Back to the campaigns
        </button>
        <p className="meta" role="status">Loading the campaign...</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="camp-detail">
        <button type="button" className="camp-back" onClick={onBack}>
          Back to the campaigns
        </button>
        <EmptyState title="The campaign did not load">
          <p className="meta">{feed.error ? describeOperatorError(feed.error) : `No campaign ${campaignId} on this master.`}</p>
          <div>
            <button type="button" onClick={feed.refetch}>
              Try again
            </button>
          </div>
        </EmptyState>
      </div>
    );
  }

  const names = runNames(config.data);

  return (
    <div className="camp-detail">
      <div className="camp-detail-head panel">
        <div className="camp-detail-title">
          <button type="button" className="camp-back" onClick={onBack}>
            Back to the campaigns
          </button>
          <h3>{detail.name}</h3>
          <StateBadge state={detail.actual_state} desired={detail.desired_state} />
          <span className={`camp-badge camp-badge--${feed.source === "live" ? "ok" : "warn"}`} title={feed.source === "live" ? "Coverage and events arrive over the live channel." : "The live channel is not delivering; the page polls the master every 4 s."}>
            {feed.source === "live" ? "live" : feed.liveStatus === "error" ? "polling, live channel refused" : "polling"}
          </span>
        </div>
        {detail.state_reason && (
          <p className={`camp-state-reason camp-state-reason--${detail.actual_state}`} role="status">
            <strong>{detail.actual_state === "stalled" ? "Why it is stalled." : "State reason."}</strong> {detail.state_reason}
          </p>
        )}
        <Disclosure
          id="campaign:details"
          variant="link"
          headingLevel={null}
          title="Campaign details"
          openTitle="Hide campaign details"
          hint={`ran for ${runDuration(detail.started_at, detail.finished_at, now)}`}
        >
          <dl className="camp-facts">
          <div>
            <dt>Campaign id</dt>
            <dd>
              <code>{detail.campaign_id}</code>
            </dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{formatDateTime(detail.created_at)}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{formatDateTime(detail.started_at)}</dd>
          </div>
          <div>
            <dt>Finished</dt>
            <dd>{detail.finished_at ? formatDateTime(detail.finished_at) : "not finished"}</dd>
          </div>
          <div>
            <dt>Ran for</dt>
            <dd>{runDuration(detail.started_at, detail.finished_at, now)}</dd>
          </div>
          <div>
            <dt>Config</dt>
            <dd>
              version {detail.config_version}, {plural(names.length || 1, "run")}
            </dd>
          </div>
        </dl>
        </Disclosure>
        <div className="camp-results-link">
          <button type="button" className="primary-btn accent" onClick={() => showCampaignResults(campaignId)} title="Verdicts, cases and recorded runs are in the Results section">
            Open the results
          </button>
        </div>
      </div>
      {feed.error && <p className="meta warning">The numbers may be stale: {describeOperatorError(feed.error)}</p>}
      <ControlsBar campaign={detail} onChanged={feed.applySummary} startBlocker={startBlocker} />
      <Totals detail={detail} />
      <CoverageTable classes={detail.classes} runNames={names} />
      <Disclosure
        id="campaign:events"
        title="Activity log"
        hint={`${events.length} ${events.length === 1 ? "event" : "events"}${feed.source === "live" ? ", live" : ""}`}
        headingLevel={3}
      >
        <EventsFeed events={events} live={feed.source === "live"} />
      </Disclosure>
      <ConfigPanel config={config.data} error={config.error} loading={config.isLoading} />
    </div>
  );
}
