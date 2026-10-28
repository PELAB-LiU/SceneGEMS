import { useState, type MouseEvent, type ReactNode } from "react";
import { formatClock } from "../scene/encounterGeometry";
import { encounterColor, RESULT_COLORS, RESULT_LABELS } from "../scene/encounterPalette";
import { renderActorName, type ActorNameMap } from "./actorNames";
import { isEncounter } from "./encounterPairs";
import {
  niceTimeStep,
  pairSummarySegments,
  ruleTag,
  type PairTrack,
  type RuleTimelineModel,
  type TimelineSegment,
} from "./ruleTimelineModel";
import "./encounterPanel.css";

export interface RuleTimelineGroup {
  key: string;
  /** Shown above the group's rows when there is more than one group. */
  label: string;
  model: RuleTimelineModel;
  names: ActorNameMap;
}

export interface RuleTimelineProps {
  groups: RuleTimelineGroup[];
  currentTime: number;
  /** Clicking the plot moves the play head here. */
  onSeek?: (timestamp: number) => void;
  selectedRelationId?: string | null;
  onSelectRelation?: (relationId: string | null) => void;
  emptyMessage?: string;
  /** Show the rule rows of pairs that were in an encounter (true) or only each pair's summary row. */
  defaultExpanded?: boolean;
}

interface Axis {
  start: number;
  end: number;
}

function percent(axis: Axis, t: number): number {
  const span = Math.max(axis.end - axis.start, 1e-9);
  return ((t - axis.start) / span) * 100;
}

function Segments<T>({
  axis,
  segments,
  color,
  title,
  label,
}: {
  axis: Axis;
  segments: TimelineSegment<T>[];
  color: (value: T) => string;
  title: (segment: TimelineSegment<T>) => string;
  label?: (value: T) => string;
}) {
  return (
    <>
      {segments.map((segment) => {
        const left = percent(axis, segment.start);
        const width = percent(axis, segment.end) - left;
        return (
          <span
            key={`${segment.start}-${segment.end}`}
            className="enc-tl-seg"
            style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color(segment.value) }}
            title={title(segment)}
          >
            {label && width > 12 ? <span className="enc-tl-seg-label">{label(segment.value)}</span> : null}
          </span>
        );
      })}
    </>
  );
}

function Cursor({ axis, t }: { axis: Axis; t: number }) {
  return <span className="enc-tl-cursor" style={{ left: `${percent(axis, t)}%` }} aria-hidden />;
}

function PairRows({
  pair,
  names,
  axis,
  currentTime,
  selected,
  expanded,
  onToggle,
  onSelect,
}: {
  pair: PairTrack;
  names: ActorNameMap;
  axis: Axis;
  currentTime: number;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  onSelect?: () => void;
}) {
  const rules = pair.rules.filter((rule) => rule.kind === "rule");
  const summary = pairSummarySegments(pair);
  const name = (id: string) => names[id] ?? id;
  const range = (segment: TimelineSegment<unknown>) =>
    `${formatClock(segment.start)} to ${formatClock(segment.end)}`;
  return (
    <div className={`enc-tl-pair${selected ? " is-selected" : ""}`}>
      <div className="enc-tl-row enc-tl-row--pair">
        <div className="enc-tl-label">
          <button
            type="button"
            className="enc-tl-toggle"
            aria-expanded={expanded}
            aria-label={expanded ? "Hide rule rows" : "Show rule rows"}
            onClick={onToggle}
            disabled={rules.length === 0}
          >
            {expanded ? "▾" : "▸"}
          </button>
          <button type="button" className="enc-tl-pair-name" onClick={onSelect} title="Select this pair">
            {renderActorName(name(pair.actor1Id))} - {renderActorName(name(pair.actor2Id))}
          </button>
        </div>
        <div className="enc-tl-plot enc-tl-plot--pair">
          <div className="enc-tl-band enc-tl-band--encounter">
            <Segments
              axis={axis}
              segments={pair.encounter.filter((segment) => isEncounter(segment.value.type))}
              color={(value) => encounterColor(value.type)}
              title={(segment) => `${segment.value.label}, ${range(segment)}`}
              label={(value) => value.label}
            />
          </div>
          <div className="enc-tl-band enc-tl-band--summary">
            <Segments
              axis={axis}
              segments={summary}
              color={(value) => RESULT_COLORS[value]}
              title={(segment) => `Worst rule state: ${RESULT_LABELS[segment.value]}, ${range(segment)}`}
            />
          </div>
          <Cursor axis={axis} t={currentTime} />
        </div>
      </div>
      {expanded
        ? rules.map((rule) => (
            <div className="enc-tl-row" key={rule.key}>
              <div className="enc-tl-label enc-tl-label--rule" title={rule.ruleName}>
                <span className="enc-tl-rule-tag">{ruleTag(rule)}</span>
                {rule.subjectActorName ? <span className="enc-muted">{renderActorName(rule.subjectActorName)}</span> : null}
                <span className="enc-tl-rule-title">{rule.title}</span>
              </div>
              <div className="enc-tl-plot">
                <Segments
                  axis={axis}
                  segments={rule.segments}
                  color={(value) => RESULT_COLORS[value]}
                  title={(segment) => `${rule.ruleName}: ${RESULT_LABELS[segment.value]}, ${range(segment)}`}
                />
                {rule.firstFailure !== null ? (
                  <span
                    className="enc-tl-first-failure"
                    style={{ left: `${percent(axis, rule.firstFailure)}%` }}
                    title={`First failed at ${formatClock(rule.firstFailure)}`}
                  />
                ) : null}
                <Cursor axis={axis} t={currentTime} />
              </div>
            </div>
          ))
        : null}
    </div>
  );
}

/**
 * Rule states over the scenario: per pair an encounter type band and the worst rule state,
 * and on demand a row per rule colored by its result, with the first failure marked.
 * Clicking the plot seeks the playback there.
 */
export function RuleTimeline({
  groups,
  currentTime,
  onSeek,
  selectedRelationId = null,
  onSelectRelation,
  emptyMessage = "No monitor results to show yet.",
  defaultExpanded = true,
}: RuleTimelineProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const filled = groups.filter((group) => group.model.pairs.length > 0);
  if (filled.length === 0) {
    return <p className="enc-muted enc-empty">{emptyMessage}</p>;
  }
  const axis: Axis = {
    start: Math.min(...filled.map((group) => group.model.start)),
    end: Math.max(...filled.map((group) => group.model.end)),
  };
  const step = niceTimeStep(axis.end - axis.start);
  const ticks: number[] = [];
  for (let t = Math.ceil(axis.start / step) * step; t <= axis.end; t += step) {
    ticks.push(t);
  }

  const seekFromPlot = (event: MouseEvent<HTMLDivElement>) => {
    if (!onSeek) return;
    const target = event.target as HTMLElement;
    const plot = target.closest(".enc-tl-plot, .enc-tl-axis-plot");
    if (!plot) return;
    const rect = plot.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(rect.width, 1)));
    onSeek(axis.start + fraction * (axis.end - axis.start));
  };

  const rows: ReactNode[] = [];
  for (const group of filled) {
    if (filled.length > 1) {
      rows.push(
        <div key={`group-${group.key}`} className="enc-tl-group">
          {group.label}
        </div>
      );
    }
    for (const pair of group.model.pairs) {
      const key = `${group.key}:${pair.relationId}`;
      const neverMet = pair.encounter.every((segment) => !isEncounter(segment.value.type));
      const isCollapsed = collapsed[key] ?? (neverMet || !defaultExpanded);
      rows.push(
        <PairRows
          key={key}
          pair={pair}
          names={group.names}
          axis={axis}
          currentTime={currentTime}
          selected={pair.relationId === selectedRelationId}
          expanded={!isCollapsed}
          onToggle={() => setCollapsed((prev) => ({ ...prev, [key]: !isCollapsed }))}
          onSelect={
            onSelectRelation
              ? () => onSelectRelation(pair.relationId === selectedRelationId ? null : pair.relationId)
              : undefined
          }
        />
      );
    }
  }

  return (
    <div className="enc-timeline" onClick={seekFromPlot}>
      <div className="enc-tl-row enc-tl-row--axis">
        <div className="enc-tl-label enc-muted">
          {formatClock(currentTime)}
        </div>
        <div className="enc-tl-axis-plot" title={onSeek ? "Click to move the play head" : undefined}>
          {ticks.map((t) => (
            <span key={t} className="enc-tl-tick" style={{ left: `${percent(axis, t)}%` }}>
              {formatClock(t)}
            </span>
          ))}
          <Cursor axis={axis} t={currentTime} />
        </div>
      </div>
      <div className="enc-tl-rows">{rows}</div>
      <div className="enc-tl-legend" aria-label="Timeline legend">
        <span>
          <i style={{ backgroundColor: RESULT_COLORS.FAILED }} /> failed
        </span>
        <span>
          <i style={{ backgroundColor: RESULT_COLORS.PASSED }} /> passed
        </span>
        <span>
          <i style={{ backgroundColor: RESULT_COLORS.UNKNOWN }} /> not applicable yet
        </span>
        <span>
          <i className="enc-tl-legend-first" /> first failure
        </span>
        <span>
          <i style={{ backgroundColor: encounterColor("HEAD_ON") }} /> head-on
        </span>
        <span>
          <i style={{ backgroundColor: encounterColor("CROSSING_FROM_PORT") }} /> crossing
        </span>
        <span>
          <i style={{ backgroundColor: encounterColor("OVERTAKING_TO_PORT") }} /> overtaking
        </span>
      </div>
    </div>
  );
}
