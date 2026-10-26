import { useEffect, useMemo, useState } from "react";
import type { EncounterViewProps } from "./encounterView";
import { frameIndexAt, KNOTS_PER_MPS, plotBounds, ruleOutcomes, vesselRows } from "./encounterStandIn";

const PLOT_WIDTH = 520;
const PLOT_HEIGHT = 300;
const TRACK_POINTS_MAX = 400;

function formatTime(seconds: number): string {
  return `${seconds.toFixed(Math.abs(seconds) < 100 && !Number.isInteger(seconds) ? 1 : 0)} s`;
}

/**
 * Stand-in for P5.8's `EncounterView`, with the same props and used only through them: a
 * time slider over the frames, a top-down plot of the tracks, each vessel's state at the
 * current frame and the rule outcomes when the frames carry monitor data. While `live` it
 * follows the latest frame until the user moves the slider away from it.
 */
export function EncounterViewStandIn({ frames, timeStep, live = false, title, initialTimestamp, onTimestampChange }: EncounterViewProps) {
  const [picked, setPicked] = useState<number | null>(() => (initialTimestamp === undefined ? null : frameIndexAt(frames, initialTimestamp)));
  const [following, setFollowing] = useState(live);
  const last = Math.max(0, frames.length - 1);
  const index = live && following ? last : Math.min(picked ?? (live ? last : 0), last);
  const frame = frames[index] ?? null;

  // Frames that start to arrive follow the latest again.
  const [wasLive, setWasLive] = useState(live);
  if (wasLive !== live) {
    setWasLive(live);
    if (live) {
      setFollowing(true);
    }
  }

  const timestamp = frame?.timestamp ?? null;
  useEffect(() => {
    if (timestamp !== null) {
      onTimestampChange?.(timestamp);
    }
  }, [timestamp, onTimestampChange]);

  const bounds = useMemo(() => plotBounds(frames), [frames]);
  const step = timeStep ?? frame?.timeStep ?? null;

  if (!frame || !bounds) {
    return (
      <section className="encounter-standin" aria-label={title ?? "Encounter"}>
        {title && <h3 className="encounter-standin-title">{title}</h3>}
        <p className="meta encounter-standin-empty">{live ? "Waiting for the first frame." : "No frames to show."}</p>
      </section>
    );
  }

  const spanX = bounds.maxX - bounds.minX;
  const spanY = bounds.maxY - bounds.minY;
  const scale = Math.min(PLOT_WIDTH / spanX, PLOT_HEIGHT / spanY);
  const offsetX = (PLOT_WIDTH - spanX * scale) / 2;
  const offsetY = (PLOT_HEIGHT - spanY * scale) / 2;
  const px = (x: number) => offsetX + (x - bounds.minX) * scale;
  const py = (y: number) => PLOT_HEIGHT - offsetY - (y - bounds.minY) * scale;

  const rows = vesselRows(frame);
  const outcomes = ruleOutcomes(frame);
  const stride = Math.max(1, Math.ceil(frames.length / TRACK_POINTS_MAX));
  const trackPoints = (id: string, from: number, to: number) => {
    const points: string[] = [];
    for (let at = from; at <= to; at += stride) {
      const state = frames[at]?.statesByActorId[id];
      if (state) {
        points.push(`${px(state.x).toFixed(1)},${py(state.y).toFixed(1)}`);
      }
    }
    return points.join(" ");
  };
  // The path so far in full colour, the rest of the frames (a planned path, say) faint.
  const tracks = rows.map((row) => ({
    id: row.id,
    ownShip: row.ownShip,
    ahead: trackPoints(row.id, Math.max(0, index - (index % stride)), last),
    behind: trackPoints(row.id, 0, index),
  }));
  const atLatest = index === last;

  return (
    <section className="encounter-standin" aria-label={title ?? "Encounter"}>
      <header className="encounter-standin-head">
        {title && <h3 className="encounter-standin-title">{title}</h3>}
        {live && <span className={`encounter-standin-live${following ? " encounter-standin-live--on" : ""}`}>{following ? "following the latest" : "paused on an earlier frame"}</span>}
      </header>

      <svg className="encounter-standin-plot" viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`} role="img" aria-label="Vessel positions and tracks, north up">
        <rect x="0" y="0" width={PLOT_WIDTH} height={PLOT_HEIGHT} className="encounter-standin-plot-bg" />
        {tracks.map((track) => (
          <polyline key={`${track.id}-ahead`} points={track.ahead} className={`encounter-standin-track encounter-standin-track--ahead${track.ownShip ? " encounter-standin-track--own" : ""}`} />
        ))}
        {tracks.map((track) => (
          <polyline key={track.id} points={track.behind} className={`encounter-standin-track${track.ownShip ? " encounter-standin-track--own" : ""}`} />
        ))}
        {rows.map((row) => {
          const x = px(row.state.x);
          const y = py(row.state.y);
          const heading = row.state.heading;
          const tipX = x + Math.cos(heading) * 16;
          const tipY = y - Math.sin(heading) * 16;
          return (
            <g key={row.id} className={`encounter-standin-vessel${row.ownShip ? " encounter-standin-vessel--own" : ""}`}>
              {row.safetyRadius > 0 && <circle cx={x} cy={y} r={Math.max(3, row.safetyRadius * scale)} className="encounter-standin-domain" />}
              <line x1={x} y1={y} x2={tipX} y2={tipY} className="encounter-standin-heading" />
              <circle cx={x} cy={y} r="4.5" className="encounter-standin-dot" />
              <text x={x + 8} y={y - 8} className="encounter-standin-label">
                {row.name}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="encounter-standin-time">
        <input
          type="range"
          min={0}
          max={last}
          step={1}
          value={index}
          disabled={frames.length < 2}
          aria-label="Time"
          onChange={(event) => {
            const next = Number(event.target.value);
            setPicked(next);
            setFollowing(live && next >= last);
          }}
        />
        <span className="encounter-standin-clock">
          t = {formatTime(frame.timestamp)}
          <span className="meta">
            {" "}
            frame {index + 1} of {frames.length}
            {step !== null ? `, ${step} s steps` : ""}
          </span>
        </span>
        {live && !atLatest && (
          <button
            type="button"
            onClick={() => {
              setPicked(last);
              setFollowing(true);
            }}
          >
            Follow the latest
          </button>
        )}
      </div>

      <table className="encounter-standin-table">
        <thead>
          <tr>
            <th>Vessel</th>
            <th>Type</th>
            <th>x, y (m)</th>
            <th>Speed</th>
            <th>Heading</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                {row.name}
                {row.ownShip && <span className="encounter-standin-own"> own ship</span>}
              </td>
              <td>{row.type}</td>
              <td className="encounter-standin-num">
                {row.state.x.toFixed(1)}, {row.state.y.toFixed(1)}
              </td>
              <td className="encounter-standin-num">
                {row.state.speed.toFixed(1)} m/s ({(row.state.speed * KNOTS_PER_MPS).toFixed(1)} kn)
              </td>
              <td className="encounter-standin-num">{row.state.heading.toFixed(2)} rad</td>
            </tr>
          ))}
        </tbody>
      </table>

      {outcomes.length > 0 ? (
        <ul className="encounter-standin-rules" aria-label="Rule outcomes">
          {outcomes.map((outcome) => (
            <li key={outcome.relationId} className={`encounter-standin-rule${outcome.failed ? " encounter-standin-rule--failed" : ""}`}>
              <span className="encounter-standin-rule-pill">{outcome.failed ? "failed" : "not failed"}</span>
              <span className="encounter-standin-rule-name">
                {outcome.relationId}
                {outcome.situation ? `, ${outcome.situation}` : ""}
              </span>
              <span className="meta">
                {outcome.passed} passed
                {outcome.failedRules.length > 0 ? `, failing: ${outcome.failedRules.join(", ")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">This frame carries no rule outcomes.</p>
      )}
    </section>
  );
}
