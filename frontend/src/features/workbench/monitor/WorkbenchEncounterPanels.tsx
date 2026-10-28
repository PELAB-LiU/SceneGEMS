import { useMemo } from "react";
import type { TrajectoryStream } from "../../../app/uiStore";
import { usePersistedState } from "../../../app/usePersistedState";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
  type PlaybackState,
} from "../../../domain/playback/playbackStore";
import { useShownPlayback } from "../../../domain/playback/playbackContext";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { PlaybackBar } from "../../encounter/PlaybackBar";
import { getShipColor, getSimulationStreamColor } from "../scene/shipColors";
import { buildActorNameMap } from "./actorNames";
import { buildPairModels } from "./encounterPairs";
import { useEncounterSelectionStore } from "./encounterSelectionStore";
import { PairCardList } from "./PairCards";
import { RuleTimeline, type RuleTimelineGroup } from "./RuleTimeline";
import { buildRuleTimeline, type RuleTimelineModel } from "./ruleTimelineModel";

const timelineCache = new WeakMap<SimulationFrame[], RuleTimelineModel>();

/** One timeline per buffered frame array, shared by the cards and the timeline strip. */
function timelineFor(frames: SimulationFrame[]): RuleTimelineModel {
  let model = timelineCache.get(frames);
  if (!model) {
    model = buildRuleTimeline(frames);
    timelineCache.set(frames, model);
  }
  return model;
}

function streamFrames(stream: TrajectoryStream) {
  return (s: PlaybackState) => (stream === "animation" ? s.frames : s.simulationFrames);
}

/** The pair cards of one playback stream (preview or simulation) of the workbench. */
export function WorkbenchPairCards({ stream }: { stream: TrajectoryStream }) {
  const frames = useShownPlayback(streamFrames(stream));
  const frame = useShownPlayback((s) => (stream === "animation" ? getCurrentFrame(s) : getCurrentSimulationFrame(s)));
  const selectedRelationId = useEncounterSelectionStore((s) => s.selectedRelationId);
  const setSelectedRelationId = useEncounterSelectionStore((s) => s.setSelectedRelationId);
  const timeline = useMemo(() => timelineFor(frames), [frames]);
  const pairs = useMemo(() => buildPairModels(frame, timeline), [frame, timeline]);
  const actors = frame?.actors;
  const colorByActorId = useMemo(
    () =>
      Object.fromEntries(
        (actors ?? []).map((actor) => [
          actor.id,
          stream === "animation" ? getShipColor(actor) : getSimulationStreamColor(actor),
        ])
      ) as Record<string, string>,
    [actors, stream]
  );
  return (
    <section className="panel enc-column-pairs" aria-label="Vessel pairs">
      <h3 className="enc-column-title">
        Vessel pairs
        {frame ? <span className="enc-muted"> at {frame.timestamp} s</span> : null}
      </h3>
      <PairCardList
        pairs={pairs}
        colorByActorId={colorByActorId}
        selectedRelationId={selectedRelationId}
        onSelectRelation={setSelectedRelationId}
        emptyMessage={frame ? "No vessel pairs in this frame." : "No frames yet."}
      />
    </section>
  );
}

interface StripControls {
  seek: (timestamp: number) => void;
  setSpeed: (speed: number) => void;
}

/**
 * Below the workbench canvas: the playback bar and the rule timeline of the preview and
 * the simulation streams, on the global playback store.
 */
export function WorkbenchEncounterStrip({ streamControls }: { streamControls: StripControls }) {
  const frames = useShownPlayback((s) => s.frames);
  const simulationFrames = useShownPlayback((s) => s.simulationFrames);
  const cursor = useShownPlayback((s) => s.playbackCursor);
  const latestTimestamp = useShownPlayback((s) => s.latestTimestamp);
  const isPlaying = useShownPlayback((s) => s.isPlaying);
  const speed = useShownPlayback((s) => s.speed);
  const followLatestPush = useShownPlayback((s) => s.followLatestPush);
  const serverTimeStep = useShownPlayback((s) => s.serverTimeStep);
  const setPlaying = useShownPlayback((s) => s.setPlaying);
  const stepBy = useShownPlayback((s) => s.stepBy);
  const followSimulationLive = useShownPlayback((s) => s.followSimulationLive);
  const selectedRelationId = useEncounterSelectionStore((s) => s.selectedRelationId);
  const setSelectedRelationId = useEncounterSelectionStore((s) => s.setSelectedRelationId);
  const [timelineOpen, setTimelineOpen] = usePersistedState("workbench-rule-timeline-open", true);

  const previewActors = frames[0]?.actors;
  const simulationActors = simulationFrames[0]?.actors;
  const previewNames = useMemo(() => buildActorNameMap(previewActors), [previewActors]);
  const simulationNames = useMemo(() => buildActorNameMap(simulationActors), [simulationActors]);
  const previewTimeline = useMemo(() => timelineFor(frames), [frames]);
  const simulationTimeline = useMemo(() => timelineFor(simulationFrames), [simulationFrames]);

  const groups: RuleTimelineGroup[] = [];
  if (frames.length > 0) {
    groups.push({ key: "preview", label: "Preview", model: previewTimeline, names: previewNames });
  }
  if (simulationFrames.length > 0) {
    groups.push({ key: "simulation", label: "Simulation", model: simulationTimeline, names: simulationNames });
  }
  const start = Math.min(frames[0]?.timestamp ?? Infinity, simulationFrames[0]?.timestamp ?? Infinity);
  const step = serverTimeStep ?? frames[0]?.timeStep ?? simulationFrames[0]?.timeStep ?? 1;

  return (
    <div className="workbench-encounter-strip">
      <div className="workbench-encounter-strip-bar">
        <PlaybackBar
          start={Number.isFinite(start) ? start : 0}
          end={latestTimestamp}
          current={cursor}
          playing={isPlaying}
          speed={speed}
          live={simulationFrames.length > 0}
          following={followLatestPush && !isPlaying}
          disabled={frames.length === 0}
          onTogglePlay={() => setPlaying(!isPlaying)}
          onSeek={streamControls.seek}
          onStep={(direction) => stepBy(direction * step)}
          onSpeed={streamControls.setSpeed}
          onFollowLive={followSimulationLive}
        />
        <button
          type="button"
          className="workbench-encounter-strip-toggle"
          aria-expanded={timelineOpen}
          onClick={() => setTimelineOpen(!timelineOpen)}
        >
          {timelineOpen ? "Hide timeline" : "Rule timeline"}
        </button>
      </div>
      {timelineOpen ? (
        <div className="workbench-encounter-timeline">
          <RuleTimeline
            groups={groups}
            currentTime={cursor}
            onSeek={frames.length > 0 ? streamControls.seek : undefined}
            selectedRelationId={selectedRelationId}
            onSelectRelation={setSelectedRelationId}
            emptyMessage="Rule states appear here once a scenario with monitor results is loaded."
            defaultExpanded={false}
          />
        </div>
      ) : null}
    </div>
  );
}
