import { WIZARD_STEPS, type WizardStepId } from "./wizardState";

/**
 * Reasons a config is refused, attached to the wizard step and field they name. The server
 * reports a reason as `<path>: <message>`, the path being the config's dotted path
 * (`scope.0.quota`, `execution.runs.1 (usv): ...`, `trajectories`, `domain.colregs_constants`);
 * a reason without a path (a YAML error) belongs to the review step.
 */

export interface Reason {
  /** The reason as the server sent it. */
  raw: string;
  step: WizardStepId;
  /** The scope entry or run the reason names (index), or null for the sections without a list. */
  entry: number | null;
  /** The field inside the entry or the section (`quota`, `stack.dt`, `scene_generation_timeout_s`), or null when it names the whole. */
  field: string | null;
  /** The config path the reason names, or null when it names none. */
  path: string | null;
  message: string;
  source: "server" | "local";
}

const REASON_PATTERN = /^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)(?: \([^)]*\))?: ([\s\S]*)$/;

const SECTION_STEPS: Record<string, WizardStepId> = {
  name: "scope",
  description: "scope",
  scope: "scope",
  domain: "domain",
  trajectories: "trajectories",
  execution: "runs",
  resources: "resources",
  policy: "policy",
};

function cleanMessage(message: string): string {
  return message.replace(/^Value error, /, "").trim();
}

/** The step, entry and field a reason names. */
export function parseReason(raw: string, source: Reason["source"] = "server"): Reason {
  const match = REASON_PATTERN.exec(raw.trim());
  if (!match) {
    return { raw, step: "review", entry: null, field: null, path: null, message: cleanMessage(raw), source };
  }
  const [, path, message] = match;
  const parts = path.split(".");
  const step = SECTION_STEPS[parts[0]] ?? "review";
  const clean = cleanMessage(message);
  if (parts[0] === "scope" && parts[1] !== undefined && /^\d+$/.test(parts[1])) {
    return { raw, step, entry: Number(parts[1]), field: parts.slice(2).join(".") || null, path, message: clean, source };
  }
  if (parts[0] === "execution" && parts[1] === "runs" && parts[2] !== undefined && /^\d+$/.test(parts[2])) {
    return { raw, step, entry: Number(parts[2]), field: parts.slice(3).join(".") || null, path, message: clean, source };
  }
  const field = parts.slice(1).join(".");
  const whole = step === "scope" || step === "review";
  return { raw, step, entry: null, field: field || (whole ? parts[0] : null), path, message: clean, source };
}

export function parseReasons(raws: readonly string[], source: Reason["source"] = "server"): Reason[] {
  return raws.map((raw) => parseReason(raw, source));
}

/** The reasons per step (every step present). */
export function reasonsByStep(reasons: readonly Reason[]): Record<WizardStepId, Reason[]> {
  const grouped = Object.fromEntries(WIZARD_STEPS.map((step) => [step, [] as Reason[]])) as Record<WizardStepId, Reason[]>;
  for (const reason of reasons) {
    grouped[reason.step].push(reason);
  }
  return grouped;
}

/** The reasons of one entry (scope entry or run), or of the step's own fields when `entry` is null. */
export function reasonsOfEntry(reasons: readonly Reason[], entry: number | null): Reason[] {
  return reasons.filter((reason) => reason.entry === entry);
}

/**
 * Sorts the reasons of an entry by the field that shows them: the most specific listed field the reason's field
 * equals or lies under; `rest` holds those no listed field shows.
 */
export function splitByField(reasons: readonly Reason[], shownFields: readonly string[]): { byField: Map<string, Reason[]>; rest: Reason[] } {
  const byField = new Map<string, Reason[]>();
  const rest: Reason[] = [];
  for (const reason of reasons) {
    let best: string | undefined;
    if (reason.field !== null) {
      for (const field of shownFields) {
        if ((reason.field === field || reason.field.startsWith(`${field}.`)) && (best === undefined || field.length > best.length)) {
          best = field;
        }
      }
    }
    if (best === undefined) {
      rest.push(reason);
    } else {
      byField.set(best, [...(byField.get(best) ?? []), reason]);
    }
  }
  return { byField, rest };
}

/** The text of a reason with the field it names in front, for a list outside the field. */
export function describeReason(reason: Reason): string {
  return reason.field ? `${reason.field}: ${reason.message}` : reason.message;
}
