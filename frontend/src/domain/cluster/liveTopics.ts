import { z } from "zod";
import {
  campaignDetailSchema,
  campaignEventSchema,
  campaignSummarySchema,
  classViewSchema,
  jobViewSchema,
  logLineSchema,
  nodeListSchema,
  nodeViewSchema,
  type CampaignDetail,
  type CampaignEvent,
  type CampaignTotals,
  type ClassView,
  type JobView,
  type LogLine,
  type NodeView,
} from "./schemas";

/**
 * Snapshots and updates of each live channel topic (design doc 5.3), with reducers that
 * fold them into a topic state. A reducer throws (a ZodError) on data that does not match.
 */

export interface LiveTopicReducer<T> {
  snapshot(raw: unknown): T;
  update(state: T, data: unknown, seq: number): T;
}

/** The raw snapshot and the most recent updates, for topics without a typed reducer. */
export interface RawTopicState {
  snapshot: unknown;
  updates: { seq: number; data: unknown }[];
}

const RAW_UPDATES_KEPT = 200;

export const rawTopicReducer: LiveTopicReducer<RawTopicState> = {
  snapshot: (raw) => ({ snapshot: raw, updates: [] }),
  update: (state, data, seq) => ({ snapshot: state.snapshot, updates: [...state.updates, { seq, data }].slice(-RAW_UPDATES_KEPT) }),
};

// nodes

export const nodesUpdateSchema = z.union([
  z.object({ node: nodeViewSchema }),
  z.object({ removed: z.string() }),
]);

function sortNodes(nodes: NodeView[]): NodeView[] {
  return [...nodes].sort((a, b) => a.name.localeCompare(b.name) || a.node_id.localeCompare(b.node_id));
}

/** Replaces the node with the same id, or adds it. */
export function upsertNode(nodes: readonly NodeView[], node: NodeView): NodeView[] {
  const others = nodes.filter((entry) => entry.node_id !== node.node_id);
  return sortNodes([...others, node]);
}

export const nodesReducer: LiveTopicReducer<NodeView[]> = {
  snapshot: (raw) => sortNodes(nodeListSchema.parse(raw)),
  update: (nodes, data) => {
    const update = nodesUpdateSchema.parse(data);
    if ("node" in update) {
      return upsertNode(nodes, update.node);
    }
    return nodes.filter((node) => node.node_id !== update.removed);
  },
};

// campaign:<id>

export const campaignUpdateSchema = z.union([
  z.object({ event: campaignEventSchema }),
  z.object({ campaign: campaignSummarySchema }),
  z.object({ classes: z.array(classViewSchema) }),
]);

export interface CampaignTopicState {
  detail: CampaignDetail;
  /** Events pushed since the snapshot, oldest first (the history comes from the events route). */
  events: CampaignEvent[];
}

const CAMPAIGN_EVENTS_KEPT = 500;

/** The totals of a campaign detail over its classes, as `campaign_views.campaign_detail_view` computes them. */
export function campaignTotals(classes: readonly ClassView[]): CampaignTotals {
  const verdicts: Record<string, number> = {};
  for (const entry of classes) {
    for (const states of Object.values(entry.verdicts)) {
      for (const [state, count] of Object.entries(states)) {
        verdicts[state] = (verdicts[state] ?? 0) + count;
      }
    }
  }
  const sum = (pick: (entry: ClassView) => number) => classes.reduce((total, entry) => total + pick(entry), 0);
  return {
    classes: classes.length,
    classes_open: classes.filter((entry) => entry.state === "open").length,
    classes_complete: classes.filter((entry) => entry.state === "complete").length,
    classes_abandoned: classes.filter((entry) => entry.state === "abandoned").length,
    quota: sum((entry) => entry.quota),
    complete: sum((entry) => entry.complete),
    dropped: sum((entry) => entry.dropped),
    in_flight: sum((entry) => entry.in_flight),
    verdicts,
  };
}

export const campaignReducer: LiveTopicReducer<CampaignTopicState> = {
  snapshot: (raw) => ({ detail: campaignDetailSchema.parse(raw), events: [] }),
  update: (state, data) => {
    const update = campaignUpdateSchema.parse(data);
    if ("event" in update) {
      if (state.events.some((event) => event.event_id === update.event.event_id)) {
        return state;
      }
      return { ...state, events: [...state.events, update.event].slice(-CAMPAIGN_EVENTS_KEPT) };
    }
    if ("campaign" in update) {
      return { ...state, detail: { ...state.detail, ...update.campaign } };
    }
    const changed = new Map(update.classes.map((entry) => [entry.class_id, entry]));
    const classes = state.detail.classes.map((entry) => changed.get(entry.class_id) ?? entry);
    for (const entry of update.classes) {
      if (!state.detail.classes.some((existing) => existing.class_id === entry.class_id)) {
        classes.push(entry);
      }
    }
    return { ...state, detail: { ...state.detail, classes, totals: campaignTotals(classes) } };
  },
};

// job:<id>

/** A job's status as the live channel pushes it (the operator API's `JobProgress` without the lease). */
export const liveJobStatusSchema = z.object({
  progress: z.number().nullable(),
  message: z.string(),
  at: z.string(),
});

export const jobSnapshotSchema = jobViewSchema.extend({
  logs: z.array(logLineSchema).default([]),
});

export const jobUpdateSchema = z.union([
  z.object({ status: liveJobStatusSchema }),
  z.object({ logs: z.array(logLineSchema) }),
  z.object({ job: jobViewSchema }),
]);

export type LiveJobStatus = z.infer<typeof liveJobStatusSchema>;

export interface JobTopicState {
  job: JobView;
  /** The latest status: from the snapshot's progress, then from status updates. */
  status: LiveJobStatus | null;
  logs: LogLine[];
}

export const JOB_LOG_LINES_KEPT = 1000;

export const jobReducer: LiveTopicReducer<JobTopicState> = {
  snapshot: (raw) => {
    const { logs, ...job } = jobSnapshotSchema.parse(raw);
    const status = job.progress ? { progress: job.progress.progress, message: job.progress.message, at: job.progress.at } : null;
    return { job, status, logs: logs.slice(-JOB_LOG_LINES_KEPT) };
  },
  update: (state, data) => {
    const update = jobUpdateSchema.parse(data);
    if ("status" in update) {
      return { ...state, status: update.status };
    }
    if ("logs" in update) {
      return { ...state, logs: [...state.logs, ...update.logs].slice(-JOB_LOG_LINES_KEPT) };
    }
    return { ...state, job: update.job };
  },
};

// instance:<node>/<instance>

export const INSTANCE_KIND_VALUES = ["scene_generation", "trajectory_generation", "simulation", "monitoring"] as const;

export const instanceSnapshotSchema = z.object({
  node_id: z.string(),
  instance: z.string(),
  kind: z.string(),
  state: z.unknown(),
});

export const sceneSampleSchema = z.object({
  kind: z.literal("scene_sample"),
  request_id: z.string(),
  valid: z.boolean(),
  evaluation_data: z.unknown(),
});

export const trajectoryPreviewSchema = z.object({
  kind: z.literal("trajectory_preview"),
  request_id: z.string(),
  trajectories: z.unknown(),
});

export const simulationFramesSchema = z.object({
  kind: z.literal("simulation_frames"),
  job_id: z.string(),
  /** Frames in the workbench's frame wire format (`gateway.serialization.serialize_monitored_frame`). */
  frames: z.array(z.unknown()),
});

export const instanceStatusSchema = z.object({
  kind: z.literal("status"),
  state: z.string(),
  message: z.string().nullable().optional(),
});

export const instanceUpdateSchema = z.discriminatedUnion("kind", [
  sceneSampleSchema,
  trajectoryPreviewSchema,
  simulationFramesSchema,
  instanceStatusSchema,
]);

export type InstanceSnapshot = z.infer<typeof instanceSnapshotSchema>;
export type SceneSample = z.infer<typeof sceneSampleSchema>;
export type TrajectoryPreview = z.infer<typeof trajectoryPreviewSchema>;

export interface InstanceTopicState {
  info: InstanceSnapshot;
  /** The latest state and message from status updates (the snapshot's state until one arrives). */
  state: unknown;
  message: string | null;
  sceneSample: SceneSample | null;
  trajectoryPreview: TrajectoryPreview | null;
  /** Simulation frames since the snapshot, oldest first, bounded. */
  frames: unknown[];
  /** Total frames received, including those no longer kept. */
  frameCount: number;
}

export const INSTANCE_FRAMES_KEPT = 5000;

export const instanceReducer: LiveTopicReducer<InstanceTopicState> = {
  snapshot: (raw) => {
    const info = instanceSnapshotSchema.parse(raw);
    return { info, state: info.state, message: null, sceneSample: null, trajectoryPreview: null, frames: [], frameCount: 0 };
  },
  update: (state, data) => {
    const update = instanceUpdateSchema.parse(data);
    switch (update.kind) {
      case "scene_sample":
        return { ...state, sceneSample: update };
      case "trajectory_preview":
        return { ...state, trajectoryPreview: update };
      case "simulation_frames":
        return {
          ...state,
          frames: [...state.frames, ...update.frames].slice(-INSTANCE_FRAMES_KEPT),
          frameCount: state.frameCount + update.frames.length,
        };
      case "status":
        return { ...state, state: update.state, message: update.message ?? null };
    }
  },
};
