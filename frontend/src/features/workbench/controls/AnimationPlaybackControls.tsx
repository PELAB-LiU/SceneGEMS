import { Disclosure } from "../../../components/Disclosure";
import { useShownPlayback } from "../../../domain/playback/playbackContext";
import { handleResetPlayback } from "./resetPlayback";

interface AnimationPlaybackControlsProps {
  /** Snap the play head to a timestamp; the shown page's store when absent. */
  seek?: (value: number) => void;
  /** Set playback speed multiplier; the shown page's store when absent. */
  setSpeed?: (value: number) => void;
  /** Optional label shown above the controls. */
  title?: string;
}

/**
 * The animation playback block (step / play / reset / scrub / speed) shared by the
 * Simulation control panel and the Trajectory Generation preview tab. It operates
 * purely on the preview `frames` stream of the shown page's playback store.
 */
export function AnimationPlaybackControls({
  seek: seekProp,
  setSpeed: setSpeedProp,
  title = "Playback",
}: AnimationPlaybackControlsProps) {
  const storeSeek = useShownPlayback((s) => s.seek);
  const storeSetSpeed = useShownPlayback((s) => s.setSpeed);
  const seek = seekProp ?? storeSeek;
  const setSpeed = setSpeedProp ?? storeSetSpeed;
  const isPlaying = useShownPlayback((s) => s.isPlaying);
  const speed = useShownPlayback((s) => s.speed);
  const currentTimestamp = useShownPlayback((s) => s.currentTimestamp);
  const latestTimestamp = useShownPlayback((s) => s.latestTimestamp);
  const setPlaying = useShownPlayback((s) => s.setPlaying);
  const stepBy = useShownPlayback((s) => s.stepBy);
  const hasFrames = useShownPlayback((s) => s.frames.length > 0);

  const stepFrameCount = Math.max(1, Math.round(speed));
  const sliderMax = Math.max(1, latestTimestamp, currentTimestamp);

  return (
    <section className="animation-control-group" aria-label="Animation playback controls">
      <h4 className="animation-control-group-title">{title}</h4>
      <div className="toolbar-row">
        <button type="button" disabled={!hasFrames} onClick={() => stepBy(-stepFrameCount)}>
          Step Back
        </button>
        <button type="button" disabled={!hasFrames} onClick={() => setPlaying(!isPlaying)}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          disabled={!hasFrames}
          onClick={() => handleResetPlayback(setPlaying, seek)}
        >
          Reset
        </button>
        <button type="button" disabled={!hasFrames} onClick={() => stepBy(stepFrameCount)}>
          Step Forward
        </button>
      </div>

      <label className="field">
        <span>Animation Time</span>
        <input
          type="range"
          min={0}
          max={sliderMax}
          value={Math.min(currentTimestamp, sliderMax)}
          disabled={!hasFrames}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </label>

      <Disclosure
        id="playback:speed"
        variant="link"
        headingLevel={null}
        title="Speed and timing"
        openTitle="Hide speed and timing"
        hint={`${speed.toFixed(1)}x`}
      >
        <label className="field">
          <span>Speed ({speed.toFixed(1)}x)</span>
          <input
            type="range"
            min={0.5}
            max={240}
            step={0.5}
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </label>
        <p className="meta animation-control-meta">
          Animation time: {currentTimestamp}s | Latest: {latestTimestamp}s
        </p>
      </Disclosure>
    </section>
  );
}
