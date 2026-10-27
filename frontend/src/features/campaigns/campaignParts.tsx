import type { ReactNode } from "react";
import type { CampaignActualState, CampaignDesiredState } from "../../domain/cluster/schemas";
import { ACTUAL_STATE_HINTS, ACTUAL_STATE_LABELS, actualStateTone, DESIRED_STATE_LABELS, isConverging, type Tone } from "./campaignModel";
import { percent } from "./campaignFormat";

/** Small pieces the list, the detail and the wizard share. */

export function StateBadge({ state, desired }: { state: CampaignActualState; desired?: CampaignDesiredState }) {
  const converging = desired !== undefined && isConverging({ actual_state: state, desired_state: desired });
  return (
    <span className="camp-state-cell">
      <span className={`camp-badge camp-badge--${actualStateTone(state)}`} title={ACTUAL_STATE_HINTS[state]}>
        {ACTUAL_STATE_LABELS[state]}
      </span>
      {converging && desired && <span className="camp-converging">asked to {DESIRED_STATE_LABELS[desired]}</span>}
    </span>
  );
}

export function ToneBadge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`camp-badge camp-badge--${tone}`} title={title}>
      {children}
    </span>
  );
}

/** A bar of complete cases against the quota, with the numbers beside it. */
export function ProgressBar({
  fraction,
  label,
  tone = "info",
  compact = false,
}: {
  fraction: number;
  label?: ReactNode;
  tone?: Tone;
  compact?: boolean;
}) {
  return (
    <div className={`camp-progress${compact ? " camp-progress--compact" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction * 100)}>
      <span className="camp-progress-track">
        <span className={`camp-progress-fill camp-progress-fill--${tone}`} style={{ width: `${Math.round(fraction * 1000) / 10}%` }} />
      </span>
      <span className="camp-progress-label">{label ?? percent(fraction)}</span>
    </div>
  );
}

export { EmptyState } from "../../components/EmptyState";

/** A tile with a label, a value and a line of detail. */
export function Tile({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: ReactNode; tone?: Tone }) {
  return (
    <div className={`stat-tile${tone && tone !== "idle" && tone !== "info" ? ` stat-tile--${tone}` : ""}`}>
      <span className="stat-tile-label">{label}</span>
      <span className="stat-tile-value">{value}</span>
      {detail && <span className="stat-tile-detail">{detail}</span>}
    </div>
  );
}
