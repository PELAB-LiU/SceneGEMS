import type { ActorKinematicState, RuleResultData, SimulationFrame } from "../../domain/simulation/types";

/** Pure helpers of the encounter view stand-in. */

export const KNOTS_PER_MPS = 1.943844;

/** Index of the frame closest to a timestamp (the first frame for an empty hint). */
export function frameIndexAt(frames: readonly SimulationFrame[], timestamp: number | undefined): number {
  if (frames.length === 0 || timestamp === undefined) {
    return 0;
  }
  let best = 0;
  let bestGap = Math.abs(frames[0].timestamp - timestamp);
  for (let index = 1; index < frames.length; index += 1) {
    const gap = Math.abs(frames[index].timestamp - timestamp);
    if (gap < bestGap) {
      best = index;
      bestGap = gap;
    }
  }
  return best;
}

export interface VesselRow {
  id: string;
  name: string;
  type: string;
  ownShip: boolean;
  state: ActorKinematicState;
  safetyRadius: number;
}

/** Each vessel with a state in the frame, own ship first. */
export function vesselRows(frame: SimulationFrame): VesselRow[] {
  const rows: VesselRow[] = [];
  for (const actor of frame.actors) {
    const state = frame.statesByActorId[actor.id];
    if (!state || !actor.isVessel) {
      continue;
    }
    rows.push({ id: actor.id, name: actor.name, type: actor.type, ownShip: actor.isOwnShip, state, safetyRadius: actor.safetyRadius });
  }
  return rows.sort((a, b) => Number(b.ownShip) - Number(a.ownShip) || a.name.localeCompare(b.name));
}

export interface RuleOutcome {
  relationId: string;
  situation: string | null;
  failed: boolean;
  passed: number;
  failedRules: string[];
  unknown: number;
}

/** The rule outcomes of a frame, one per relation (empty when the frame carries no monitor data). */
export function ruleOutcomes(frame: SimulationFrame): RuleOutcome[] {
  const labels = new Map(frame.situationContexts.map((context) => [context.relationId, context.situationLabel]));
  return frame.ruleResults.map((result: RuleResultData) => ({
    relationId: result.relationId,
    situation: labels.get(result.relationId) ?? null,
    failed: result.overallStatus === "FAILED",
    passed: result.evaluations.filter((entry) => entry.result === "PASSED").length,
    failedRules: result.failedRules.length > 0 ? result.failedRules : result.evaluations.filter((entry) => entry.result === "FAILED").map((entry) => entry.ruleName),
    unknown: result.evaluations.filter((entry) => entry.result === "UNKNOWN").length,
  }));
}

export interface PlotBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** The bounds of every vessel position in the frames, padded so a single point still has a view. */
export function plotBounds(frames: readonly SimulationFrame[]): PlotBounds | null {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const frame of frames) {
    for (const state of Object.values(frame.statesByActorId)) {
      if (!Number.isFinite(state.x) || !Number.isFinite(state.y)) {
        continue;
      }
      minX = Math.min(minX, state.x);
      maxX = Math.max(maxX, state.x);
      minY = Math.min(minY, state.y);
      maxY = Math.max(maxY, state.y);
    }
  }
  if (!Number.isFinite(minX)) {
    return null;
  }
  const pad = Math.max(maxX - minX, maxY - minY, 50) * 0.12;
  return { minX: minX - pad, maxX: maxX + pad, minY: minY - pad, maxY: maxY + pad };
}
