import { formatClock } from "../workbench/scene/encounterGeometry";
import { PLAYBACK_SPEEDS } from "./encounterPlayback";
import "./encounterView.css";

export interface PlaybackBarProps {
  start: number;
  end: number;
  /** Play head in scenario seconds. */
  current: number;
  playing: boolean;
  speed: number;
  /** Frames keep arriving: shows the Live button. */
  live?: boolean;
  /** The play head follows the latest frame. */
  following?: boolean;
  disabled?: boolean;
  onTogglePlay: () => void;
  onSeek: (timestamp: number) => void;
  onStep: (direction: 1 | -1) => void;
  onSpeed: (speed: number) => void;
  onFollowLive?: () => void;
}

/** Compact transport: step, play or pause, the time slider, speed and Live. */
export function PlaybackBar({
  start,
  end,
  current,
  playing,
  speed,
  live = false,
  following = false,
  disabled = false,
  onTogglePlay,
  onSeek,
  onStep,
  onSpeed,
  onFollowLive,
}: PlaybackBarProps) {
  const speeds = (PLAYBACK_SPEEDS as readonly number[]).includes(speed)
    ? PLAYBACK_SPEEDS
    : [...PLAYBACK_SPEEDS, speed].sort((a, b) => a - b);
  return (
    <div className="enc-playback" role="group" aria-label="Playback">
      <button type="button" disabled={disabled} onClick={() => onStep(-1)} title="One step back" aria-label="Step back">
        ◀◀
      </button>
      <button type="button" className="enc-playback-play primary-btn" disabled={disabled} onClick={onTogglePlay}>
        {playing ? "Pause" : "Play"}
      </button>
      <button type="button" disabled={disabled} onClick={() => onStep(1)} title="One step forward" aria-label="Step forward">
        ▶▶
      </button>
      <span className="enc-playback-time" aria-live="off">
        {formatClock(current)} / {formatClock(end)}
      </span>
      <input
        className="enc-playback-slider"
        type="range"
        min={start}
        max={Math.max(end, start + 1e-6)}
        step="any"
        value={Math.min(Math.max(current, start), end)}
        disabled={disabled}
        aria-label="Scenario time"
        onChange={(event) => onSeek(Number(event.target.value))}
      />
      <label>
        <span className="enc-sr-only">Playback speed</span>
        <select value={speed} onChange={(event) => onSpeed(Number(event.target.value))} aria-label="Playback speed">
          {speeds.map((value) => (
            <option key={value} value={value}>
              {value}x
            </option>
          ))}
        </select>
      </label>
      {live && onFollowLive ? (
        <button
          type="button"
          className={`enc-playback-live${following ? " is-active" : ""}`}
          aria-pressed={following}
          onClick={onFollowLive}
          title="Follow the latest frame"
        >
          Live
        </button>
      ) : null}
    </div>
  );
}
