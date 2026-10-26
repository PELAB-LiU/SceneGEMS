import type { RuleResult } from "../../../domain/simulation/types";
import type { VesselRole } from "../monitor/encounterPairs";

/**
 * Colors of the encounter canvas, cards and timeline. The canvas uses literal colors
 * rather than CSS variables so a screenshot (the SVG rasterized on its own) keeps them.
 */
export const CANVAS_COLORS = {
  sea: "#0a1628",
  ring: "rgba(148, 163, 184, 0.32)",
  ringLabel: "#8fa3bf",
  bearingTick: "rgba(148, 163, 184, 0.55)",
  bearingLabel: "#9fb1c9",
  hullStroke: "#e2e8f0",
  labelText: "#e2e8f0",
  labelMuted: "#9fb1c9",
  labelBackground: "rgba(2, 6, 23, 0.72)",
  selection: "#f8fafc",
  cpaNeutral: "#cbd5e1",
  cpaWarn: "#fbbf24",
  cpaDanger: "#f87171",
  legendBackground: "rgba(2, 6, 23, 0.8)",
  legendBorder: "rgba(148, 163, 184, 0.35)",
} as const;

export const CANVAS_FONT = '"IBM Plex Sans", "Segoe UI", Helvetica, sans-serif';

export const ROLE_COLORS: Record<VesselRole, string> = {
  "give-way": "#f59e0b",
  "stand-on": "#60a5fa",
};

export const ROLE_CODES: Record<VesselRole, string> = {
  "give-way": "GW",
  "stand-on": "SO",
};

export const RESULT_COLORS: Record<RuleResult, string> = {
  FAILED: "#ef4444",
  UNKNOWN: "#475569",
  PASSED: "#22c55e",
};

export const RESULT_LABELS: Record<RuleResult, string> = {
  FAILED: "failed",
  UNKNOWN: "not applicable yet",
  PASSED: "passed",
};

/** Encounter type colors on the timeline's encounter row. */
export function encounterColor(situationType: string): string {
  const type = situationType.toUpperCase();
  if (type === "HEAD_ON") return "#c084fc";
  if (type.startsWith("TWO_WAY")) return "#f472b6";
  if (type.startsWith("CROSSING")) return "#38bdf8";
  if (type.startsWith("OVERTAKING")) return "#2dd4bf";
  return "#1e293b";
}
