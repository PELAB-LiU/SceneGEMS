import type { RuleEvaluation, RuleResult, SimulationFrame } from "../../domain/simulation/types";
import { compassCourse, metersPerSecondToKnots } from "./resultsFormat";

/** Pure reading of a monitor frame for the recorded run stand-in. */

export interface VesselRow {
  id: string;
  name: string;
  type: string;
  isOwnShip: boolean;
  x: number;
  y: number;
  speedMs: number;
  speedKn: number;
  /** Compass course, degrees. */
  courseDeg: number;
  /** One text per encounter the vessel is in: `give way to OS_0`. */
  roles: string[];
}

export interface RelationRow {
  relationId: string;
  /** `OS_0 and TS_1`. */
  label: string;
  /** Encounter type the monitor reports, e.g. `Crossing from starboard`. */
  situation: string | null;
  distance: number | null;
  dcpa: number | null;
  tcpa: number | null;
  failed: boolean;
  rules: RuleRow[];
}

export interface RuleRow {
  name: string;
  /** The vessel the rule constrains, empty when it applies to the encounter. */
  subject: string;
  result: RuleResult;
  kind: RuleEvaluation["kind"];
}

/** The index of the frame closest to `timestamp`; the frames are ordered by time. */
export function nearestFrameIndex(frames: readonly SimulationFrame[], timestamp: number): number {
  if (frames.length === 0) {
    return 0;
  }
  let low = 0;
  let high = frames.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (frames[mid].timestamp < timestamp) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  if (low > 0 && Math.abs(frames[low - 1].timestamp - timestamp) <= Math.abs(frames[low].timestamp - timestamp)) {
    return low - 1;
  }
  return low;
}

export function actorName(frame: SimulationFrame, actorId: string): string {
  return frame.actors.find((actor) => actor.id === actorId)?.name ?? actorId;
}

/** `0->1` as `OS_0 and TS_1` with the vessels' names. */
export function relationLabel(frame: SimulationFrame, relationId: string): string {
  const parts = relationId.split("->");
  if (parts.length !== 2) {
    return relationId;
  }
  return `${actorName(frame, parts[0])} and ${actorName(frame, parts[1])}`;
}

const RESULT_ORDER: Record<RuleResult, number> = { FAILED: 0, UNKNOWN: 1, PASSED: 2 };

export function relationRows(frame: SimulationFrame): RelationRow[] {
  const rows = new Map<string, RelationRow>();
  const ensure = (relationId: string): RelationRow => {
    let row = rows.get(relationId);
    if (!row) {
      row = { relationId, label: relationLabel(frame, relationId), situation: null, distance: null, dcpa: null, tcpa: null, failed: false, rules: [] };
      rows.set(relationId, row);
    }
    return row;
  };
  for (const context of frame.situationContexts) {
    ensure(context.relationId).situation = context.situationLabel || context.situationType;
  }
  for (const result of frame.ruleResults) {
    const row = ensure(result.relationId);
    row.failed = result.overallStatus === "FAILED" || result.evaluations.some((evaluation) => evaluation.result === "FAILED");
    row.rules = result.evaluations
      .map((evaluation) => ({ name: evaluation.ruleName, subject: evaluation.subjectActorName, result: evaluation.result, kind: evaluation.kind }))
      .sort((a, b) => RESULT_ORDER[a.result] - RESULT_ORDER[b.result] || a.name.localeCompare(b.name));
  }
  const metrics = frame.metrics;
  for (const row of rows.values()) {
    row.distance = metrics?.distanceByRelationId?.[row.relationId] ?? null;
    row.dcpa = metrics?.dcpaByRelationId?.[row.relationId] ?? null;
    row.tcpa = metrics?.tcpaByRelationId?.[row.relationId] ?? null;
  }
  return [...rows.values()].sort((a, b) => Number(b.failed) - Number(a.failed) || a.relationId.localeCompare(b.relationId));
}

export function vesselRows(frame: SimulationFrame): VesselRow[] {
  const roles = new Map<string, string[]>();
  for (const context of frame.situationContexts) {
    for (const [actorId, giveWay] of Object.entries(context.isGiveWayByActorId)) {
      const other = [context.actor1Id, context.actor2Id].find((id) => id !== actorId);
      const text = `${giveWay ? "give way to" : "stands on for"} ${other === undefined ? "?" : actorName(frame, other)}`;
      roles.set(actorId, [...(roles.get(actorId) ?? []), text]);
    }
  }
  return frame.actors
    .filter((actor) => actor.isVessel && frame.statesByActorId[actor.id] !== undefined)
    .map((actor) => {
      const state = frame.statesByActorId[actor.id];
      return {
        id: actor.id,
        name: actor.name,
        type: actor.type,
        isOwnShip: actor.isOwnShip,
        x: state.x,
        y: state.y,
        speedMs: state.speed,
        speedKn: metersPerSecondToKnots(state.speed),
        courseDeg: compassCourse(state.heading),
        roles: roles.get(actor.id) ?? [],
      };
    })
    .sort((a, b) => Number(b.isOwnShip) - Number(a.isOwnShip) || a.name.localeCompare(b.name));
}

/** Whether any rule has failed at each frame. */
export function failedFlags(frames: readonly SimulationFrame[]): boolean[] {
  return frames.map((frame) => frame.ruleResults.some((result) => result.overallStatus === "FAILED" || result.evaluations.some((evaluation) => evaluation.result === "FAILED")));
}

/** The index of the first frame with a failed rule, or -1. */
export function firstFailureIndex(frames: readonly SimulationFrame[]): number {
  return failedFlags(frames).indexOf(true);
}

export interface TrackPoint {
  x: number;
  y: number;
}

export interface Track {
  id: string;
  name: string;
  isOwnShip: boolean;
  points: TrackPoint[];
}

export interface TrackBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** Every vessel's positions over the frames (at most `maxPoints` per track) and the bounds of all of them. */
export function buildTracks(frames: readonly SimulationFrame[], maxPoints = 400): { tracks: Track[]; bounds: TrackBounds | null } {
  const byId = new Map<string, Track>();
  const stride = Math.max(1, Math.ceil(frames.length / maxPoints));
  let bounds: TrackBounds | null = null;
  frames.forEach((frame, index) => {
    for (const actor of frame.actors) {
      const state = frame.statesByActorId[actor.id];
      if (!actor.isVessel || state === undefined) {
        continue;
      }
      let track = byId.get(actor.id);
      if (!track) {
        track = { id: actor.id, name: actor.name, isOwnShip: actor.isOwnShip, points: [] };
        byId.set(actor.id, track);
      }
      if (index % stride === 0 || index === frames.length - 1) {
        track.points.push({ x: state.x, y: state.y });
      }
      bounds = bounds
        ? { minX: Math.min(bounds.minX, state.x), maxX: Math.max(bounds.maxX, state.x), minY: Math.min(bounds.minY, state.y), maxY: Math.max(bounds.maxY, state.y) }
        : { minX: state.x, maxX: state.x, minY: state.y, maxY: state.y };
    }
  });
  const tracks = [...byId.values()].sort((a, b) => Number(b.isOwnShip) - Number(a.isOwnShip) || a.name.localeCompare(b.name));
  return { tracks, bounds };
}
