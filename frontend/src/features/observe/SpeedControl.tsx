import { SPEED_CHOICES } from "./speedChoices";

interface SpeedControlProps {
  /** The speed this browser asked for. */
  requested: number;
  /** The pace the master reports (`observed_speed` of the instance), null while it reports none. */
  reported: number | null | undefined;
  disabled?: boolean;
  onChange: (speed: number) => void;
}

/** The pace of an observed simulation, as multiples of real time. The pace changes wall time only. */
export function SpeedControl({ requested, reported, disabled, onChange }: SpeedControlProps) {
  const settled = reported !== null && reported !== undefined && reported === requested;
  return (
    <div className="observe-speed">
      <div className="observe-speed-head">
        <span className="observe-speed-label" id="observe-speed-label">
          Pace
        </span>
        <span className="meta" role="status">
          {reported === null || reported === undefined
            ? "The master reports no pace yet."
            : settled
              ? `The master paces the run at ${reported}x real time.`
              : `The master reports ${reported}x real time, you asked for ${requested}x.`}
        </span>
      </div>
      <div className="observe-speed-choices" role="group" aria-labelledby="observe-speed-label">
        {SPEED_CHOICES.map((speed) => (
          <button
            key={speed}
            type="button"
            className={`observe-speed-choice${speed === requested ? " observe-speed-choice--active" : ""}`}
            aria-pressed={speed === requested}
            disabled={disabled}
            onClick={() => onChange(speed)}
          >
            {speed}x
          </button>
        ))}
      </div>
      <p className="meta">The pace changes how long the run takes, not its result. The latest request counts for everyone watching this run.</p>
    </div>
  );
}
