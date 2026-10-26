import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SimulationFrame } from "../../domain/simulation/types";
import { buildTracks, failedFlags, nearestFrameIndex, relationRows, vesselRows } from "./frameView";
import { formatSeconds } from "./resultsFormat";

/**
 * Stand-in for P5.8's `features/encounter/EncounterView`, with exactly its props (design doc
 * 5.3, "Wave 2 contracts"). The Results section uses it only through these props, so the wave 2
 * merge replaces the import in `RecordedRun.tsx` and nothing else. It shows a time slider with
 * the failed stretches marked, a top-down track plot, each vessel's state at the current frame
 * and the rule outcomes of that frame per encounter.
 */
export interface EncounterViewProps {
  /** Frames in the workbench's frame wire format, as `domain/simulation/protocol.ts` parses them. */
  frames: SimulationFrame[];
  /** Seconds between frames, when known. */
  timeStep?: number | null;
  /** Frames keep arriving: follow the latest until the user scrubs. */
  live?: boolean;
  title?: string;
  initialTimestamp?: number;
  onTimestampChange?: (timestamp: number) => void;
}

const SPEEDS = [1, 5, 20] as const;
const TRACK_COLORS = ["#38bdf8", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#fb7185"];
const PLOT_WIDTH = 440;
const PLOT_HEIGHT = 280;
const PLOT_PAD = 24;

function TrackPlot({ frames, index }: { frames: SimulationFrame[]; index: number }) {
  const { tracks, bounds } = useMemo(() => buildTracks(frames), [frames]);
  if (!bounds) {
    return null;
  }
  const spanX = Math.max(bounds.maxX - bounds.minX, 1);
  const spanY = Math.max(bounds.maxY - bounds.minY, 1);
  const scale = Math.min((PLOT_WIDTH - 2 * PLOT_PAD) / spanX, (PLOT_HEIGHT - 2 * PLOT_PAD) / spanY);
  const offsetX = (PLOT_WIDTH - spanX * scale) / 2;
  const offsetY = (PLOT_HEIGHT - spanY * scale) / 2;
  const px = (x: number) => offsetX + (x - bounds.minX) * scale;
  const py = (y: number) => PLOT_HEIGHT - offsetY - (y - bounds.minY) * scale;
  const frame = frames[index];
  return (
    <svg className="run-plot" viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`} role="img" aria-label="Tracks of the vessels with their positions at the current time">
      {tracks.map((track, i) => (
        <polyline
          key={track.id}
          points={track.points.map((point) => `${px(point.x).toFixed(1)},${py(point.y).toFixed(1)}`).join(" ")}
          fill="none"
          stroke={TRACK_COLORS[i % TRACK_COLORS.length]}
          strokeOpacity={0.45}
          strokeWidth={1.5}
        />
      ))}
      {tracks.map((track, i) => {
        const state = frame?.statesByActorId[track.id];
        if (!state) {
          return null;
        }
        const color = TRACK_COLORS[i % TRACK_COLORS.length];
        const x = px(state.x);
        const y = py(state.y);
        const length = 16;
        return (
          <g key={track.id}>
            <line x1={x} y1={y} x2={x + Math.cos(state.heading) * length} y2={y - Math.sin(state.heading) * length} stroke={color} strokeWidth={2} />
            <circle cx={x} cy={y} r={5} fill={color} stroke="var(--bg-panel)" strokeWidth={1.5} />
            <text x={x + 8} y={y - 8} fill={color} fontSize={11} fontWeight={600}>
              {track.name}
            </text>
          </g>
        );
      })}
      <text x={PLOT_PAD / 2} y={PLOT_HEIGHT - 6} fill="var(--text-faint)" fontSize={10}>
        east to the right, north up; {Math.round(spanX)} by {Math.round(spanY)} m
      </text>
    </svg>
  );
}

function FailureStrip({ flags, index, onSelect }: { flags: boolean[]; index: number; onSelect: (index: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const select = (clientX: number) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0 || flags.length === 0) {
      return;
    }
    onSelect(Math.min(flags.length - 1, Math.max(0, Math.round(((clientX - box.left) / box.width) * (flags.length - 1)))));
  };
  const segments = useMemo(() => {
    const runs: { from: number; to: number }[] = [];
    flags.forEach((failed, i) => {
      if (!failed) {
        return;
      }
      const last = runs[runs.length - 1];
      if (last && last.to === i - 1) {
        last.to = i;
      } else {
        runs.push({ from: i, to: i });
      }
    });
    return runs;
  }, [flags]);
  const denominator = Math.max(1, flags.length - 1);
  return (
    <div
      ref={ref}
      className="run-strip"
      title="Stretches where a rule has failed"
      onClick={(event) => select(event.clientX)}
    >
      {segments.map((segment) => (
        <span
          key={segment.from}
          className="run-strip-failed"
          style={{ left: `${(segment.from / denominator) * 100}%`, width: `max(2px, ${((segment.to - segment.from) / denominator) * 100}%)` }}
        />
      ))}
      <span className="run-strip-cursor" style={{ left: `${(index / denominator) * 100}%` }} />
    </div>
  );
}

function formatMeters(value: number | null): string {
  return value === null ? "-" : `${Math.round(value * 10) / 10} m`;
}

export function RunFramesStandIn({ frames, timeStep = null, live = false, title, initialTimestamp, onTimestampChange }: EncounterViewProps) {
  const [index, setIndex] = useState(() => (initialTimestamp === undefined ? 0 : nearestFrameIndex(frames, initialTimestamp)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(5);
  const [scrubbed, setScrubbed] = useState(false);
  const notify = useRef(onTimestampChange);
  useEffect(() => {
    notify.current = onTimestampChange;
  }, [onTimestampChange]);

  const last = Math.max(0, frames.length - 1);
  const current = Math.min(live && !scrubbed ? last : index, last);
  const currentRef = useRef(current);
  useEffect(() => {
    currentRef.current = current;
  }, [current]);
  const frame: SimulationFrame | undefined = frames[current];
  const flags = useMemo(() => failedFlags(frames), [frames]);
  const stepSeconds = timeStep ?? frame?.timeStep ?? 1;

  const select = useCallback(
    (next: number) => {
      const bounded = Math.min(Math.max(0, next), Math.max(0, frames.length - 1));
      setIndex(bounded);
      setScrubbed(true);
      const target = frames[bounded];
      if (target) {
        notify.current?.(target.timestamp);
      }
    },
    [frames]
  );

  useEffect(() => {
    if (!playing) {
      return undefined;
    }
    const delay = Math.max(30, (stepSeconds * 1000) / speed);
    const timer = setInterval(() => {
      if (currentRef.current >= last) {
        setPlaying(false);
        return;
      }
      select(currentRef.current + 1);
    }, delay);
    return () => clearInterval(timer);
  }, [playing, speed, stepSeconds, last, select]);

  if (!frame) {
    return <p className="meta">No frames to show.</p>;
  }
  const vessels = vesselRows(frame);
  const relations = relationRows(frame);
  const failedNow = relations.filter((relation) => relation.failed).length;
  const firstFailed = flags.indexOf(true);

  return (
    <div className="run-view">
      <div className="run-view-head">
        <h4>{title ?? "Recorded run"}</h4>
        <span className="meta">
          {frames.length} frames, every {formatSeconds(stepSeconds)}
          {live ? ", live" : ""}
        </span>
        <span className={`run-chip ${failedNow > 0 ? "run-chip--failed" : "run-chip--passed"}`}>
          {failedNow > 0 ? `${failedNow} ${failedNow === 1 ? "encounter" : "encounters"} with a failed rule` : "no failed rule at this time"}
        </span>
      </div>

      <div className="run-controls">
        <button type="button" onClick={() => setPlaying((value) => !value)} disabled={frames.length < 2} aria-label={playing ? "Pause" : "Play"}>
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={() => select(current - 1)} disabled={current <= 0} aria-label="Previous frame">
          Back
        </button>
        <button type="button" onClick={() => select(current + 1)} disabled={current >= last} aria-label="Next frame">
          Forward
        </button>
        <input
          className="run-slider"
          type="range"
          min={0}
          max={last}
          step={1}
          value={current}
          onChange={(event) => select(Number(event.target.value))}
          aria-label="Time"
        />
        <span className="run-time">
          <strong>{formatSeconds(frame.timestamp)}</strong>
          <span className="meta"> of {formatSeconds(frames[last].timestamp)}</span>
        </span>
        <label className="run-speed">
          Speed
          <select value={speed} onChange={(event) => setSpeed(Number(event.target.value) as (typeof SPEEDS)[number])}>
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value} times
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => select(firstFailed)} disabled={firstFailed < 0} title="Jump to the first frame with a failed rule">
          First failure
        </button>
      </div>
      <FailureStrip flags={flags} index={current} onSelect={select} />

      <div className="run-grid">
        <TrackPlot frames={frames} index={current} />
        <div className="run-side">
          <table className="run-table" aria-label="Vessels at this time">
            <thead>
              <tr>
                <th>Vessel</th>
                <th>Type</th>
                <th>x, y (m)</th>
                <th>Speed</th>
                <th>Course</th>
                <th>Role</th>
              </tr>
            </thead>
            <tbody>
              {vessels.map((vessel) => (
                <tr key={vessel.id}>
                  <td>
                    <strong>{vessel.name}</strong>
                    {vessel.isOwnShip && <span className="run-tag">own ship</span>}
                  </td>
                  <td>{vessel.type}</td>
                  <td className="mono">
                    {vessel.x.toFixed(1)}, {vessel.y.toFixed(1)}
                  </td>
                  <td className="mono">
                    {vessel.speedMs.toFixed(1)} m/s ({vessel.speedKn.toFixed(1)} kn)
                  </td>
                  <td className="mono">{vessel.courseDeg.toFixed(0)} deg</td>
                  <td>{vessel.roles.length > 0 ? vessel.roles.join("; ") : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="run-relations">
        {relations.length === 0 && <p className="meta">The monitor reports no encounter at this time.</p>}
        {relations.map((relation) => (
          <section key={relation.relationId} className={`run-relation${relation.failed ? " run-relation--failed" : ""}`}>
            <header>
              <strong>{relation.label}</strong>
              {relation.situation && <span className="run-tag">{relation.situation}</span>}
              <span className="meta">
                distance {formatMeters(relation.distance)}, CPA {formatMeters(relation.dcpa)}, TCPA {formatSeconds(relation.tcpa)}
              </span>
            </header>
            {relation.rules.length === 0 ? (
              <p className="meta">No rule is evaluated for this encounter at this time.</p>
            ) : (
              <ul className="run-rules">
                {relation.rules.map((rule) => (
                  <li key={`${rule.name}|${rule.subject}`} className={`run-rule run-rule--${rule.result.toLowerCase()}`}>
                    <span className="run-result">{rule.result.toLowerCase()}</span>
                    <span>{rule.name}</span>
                    {rule.subject && <span className="meta">{rule.subject}</span>}
                    {rule.kind === "suggestion" && <span className="run-tag">suggestion</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
