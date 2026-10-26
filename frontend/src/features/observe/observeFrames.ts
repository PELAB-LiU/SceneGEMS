import type { SceneSample, TrajectoryPreview } from "../../domain/cluster/liveTopics";
import { buildFramesFromTrajectoryData } from "../../domain/sceneGeneration/parseEvaluationDataFile";
import { parseFrame } from "../../domain/simulation/protocol";
import type { SimulationFrame } from "../../domain/simulation/types";

/**
 * Conversions from the live channel's instance updates to frames in the workbench's frame
 * wire format, through the workbench's own parsing (`parseFrame`, `buildFramesFromTrajectoryData`).
 */

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export interface ConvertedFrames {
  frames: SimulationFrame[];
  /** Why nothing could be shown, when the payload did not parse. */
  error: string | null;
}

/** A scene sample's scene (one frame of the workbench's wire format) as a one-frame list. */
export function sceneSampleFrames(sample: SceneSample | null): ConvertedFrames {
  if (!sample || sample.scene === undefined || sample.scene === null) {
    return { frames: [], error: null };
  }
  try {
    return { frames: [parseFrame(sample.scene)], error: null };
  } catch (error) {
    return { frames: [], error: `The scene could not be read: ${describe(error)}` };
  }
}

/** A trajectory preview's paths over time: one frame per planned scene, as the workbench builds them. */
export function trajectoryPreviewFrames(preview: TrajectoryPreview | null): ConvertedFrames {
  if (!preview || preview.trajectories === undefined || preview.trajectories === null) {
    return { frames: [], error: null };
  }
  try {
    return { frames: buildFramesFromTrajectoryData(preview.trajectories), error: null };
  } catch (error) {
    return { frames: [], error: `The trajectories could not be read: ${describe(error)}` };
  }
}

/**
 * The parsed frames of a live simulation. The topic state keeps the raw frames bounded
 * (`INSTANCE_FRAMES_KEPT`) and counts every frame received; this parses only the frames that
 * arrived since the last call, keeps the same bound and starts over when the count goes
 * back (a new snapshot).
 */
export class FrameBuffer {
  private frames: SimulationFrame[] = [];
  private parsedCount = 0;
  private skipped = 0;
  private readonly limit: number;

  constructor(limit: number) {
    this.limit = limit;
  }

  /** Number of frames that did not parse and were left out. */
  get skippedCount(): number {
    return this.skipped;
  }

  /** The parsed frames for `raw` (the topic's kept frames, oldest first) and the total received. */
  sync(raw: readonly unknown[], received: number): SimulationFrame[] {
    if (received < this.parsedCount) {
      this.frames = [];
      this.parsedCount = 0;
      this.skipped = 0;
    }
    const fresh = Math.min(received - this.parsedCount, raw.length);
    if (fresh <= 0) {
      return this.frames;
    }
    const added: SimulationFrame[] = [];
    for (const entry of raw.slice(raw.length - fresh)) {
      try {
        added.push(parseFrame(entry));
      } catch {
        this.skipped += 1;
      }
    }
    this.parsedCount = received;
    this.frames = [...this.frames, ...added].slice(-this.limit);
    return this.frames;
  }
}

export interface EvaluationFact {
  label: string;
  value: string;
}

function formatFact(value: unknown): string | null {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "string") {
    return value.length > 60 ? `${value.slice(0, 57)}...` : value;
  }
  if (Array.isArray(value)) {
    return `${value.length} entries`;
  }
  return null;
}

/** A few facts from a scene sample's evaluation data: its scalar entries and list lengths, in order. */
export function evaluationFacts(data: unknown, limit = 6): EvaluationFact[] {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return [];
  }
  const facts: EvaluationFact[] = [];
  for (const [key, value] of Object.entries(data)) {
    const text = formatFact(value);
    if (text !== null) {
      facts.push({ label: key.replace(/[_-]+/g, " "), value: text });
    }
    if (facts.length >= limit) {
      break;
    }
  }
  return facts;
}
