import { parseDocument } from "yaml";
import { findGenerator, findStack, isSet, supportsEnvironment, type BuilderCatalog } from "./configBuilder";
import type { Reason } from "./reasons";
import type { WizardDraft, WizardStepId } from "./wizardState";

/**
 * Problems of a draft the browser can see without the master: a missing name, an empty scope entry, a
 * run without an available stack, a parameter the stack requires, domain text that is not YAML. They
 * come in the shape of the server's reasons so the steps show both the same way. The master still
 * validates everything (the catalog, the resolver, every range).
 */

function local(step: WizardStepId, entry: number | null, field: string | null, message: string): Reason {
  const path = entry === null ? field : field ? `${entry}.${field}` : String(entry);
  return { raw: message, step, entry, field, path, message, source: "local" };
}

function yamlProblem(text: string): string | null {
  const document = parseDocument(text, { uniqueKeys: true });
  if (document.errors.length > 0) {
    return document.errors[0].message.split("\n")[0];
  }
  const value: unknown = document.toJS();
  if (typeof value !== "object" || value === null || Array.isArray(value) || Object.keys(value).length === 0) {
    return "expected a YAML mapping with at least one entry";
  }
  return null;
}

/** The problems found in the draft; `catalog` is null while the master's stack catalog is not loaded. */
export function checkDraft(draft: WizardDraft, catalog: BuilderCatalog | null): Reason[] {
  const reasons: Reason[] = [];
  if (draft.name.trim().length === 0) {
    reasons.push(local("scope", null, "name", "Give the campaign a name."));
  }
  draft.scope.forEach((entry, index) => {
    if (entry.classes.length === 0 && entry.patterns.length === 0) {
      reasons.push(local("scope", index, null, "Choose classes or a folder pattern."));
    }
    if (entry.quota === null || entry.quota < 1) {
      reasons.push(local("scope", index, "quota", "The quota is at least 1."));
    }
    if (entry.failureBudget !== null && entry.failureBudget < 0) {
      reasons.push(local("scope", index, "failure_budget", "The failure budget is 0 or more."));
    }
  });
  if (draft.domain.custom) {
    const texts: [string, string][] = [
      ["colregs_constants", draft.domain.colregsConstants],
      ["vessel_types", draft.domain.vesselTypes],
      ["obstacle_types", draft.domain.obstacleTypes],
    ];
    for (const [field, text] of texts) {
      const problem = text.trim().length === 0 ? "expected a YAML mapping with at least one entry" : yamlProblem(text);
      if (problem) {
        reasons.push(local("domain", null, field, `Not valid YAML: ${problem}`));
      }
    }
  }
  if (!isSet(draft.domain.sceneGenerationTimeoutS) || (draft.domain.sceneGenerationTimeoutS ?? 0) <= 0) {
    reasons.push(local("domain", null, "scene_generation_timeout_s", "The timeout is above 0 seconds."));
  }
  if (catalog) {
    const generator = findGenerator(catalog, draft.trajectories.generator);
    if (!generator) {
      reasons.push(local("trajectories", null, "generator", `The master offers no generator ${draft.trajectories.generator}.`));
    } else {
      for (const parameter of generator.parameters) {
        if (parameter.required && !isSet(draft.trajectories.parameters[parameter.key])) {
          reasons.push(local("trajectories", null, parameter.key, `${parameter.key} is required.`));
        }
      }
    }
  }
  if (!isSet(draft.trajectories.timeoutS) || (draft.trajectories.timeoutS ?? 0) <= 0) {
    reasons.push(local("trajectories", null, "timeout_s", "The timeout is above 0 seconds."));
  }
  draft.runs.forEach((run, index) => {
    const stack = catalog ? findStack(catalog, run.stackId) : undefined;
    if (catalog && !run.stackId) {
      reasons.push(local("runs", index, "stack", "Choose a stack."));
    } else if (catalog && !stack) {
      reasons.push(local("runs", index, "stack", `The master offers no stack ${run.stackId}.`));
    } else if (stack && !stack.available) {
      reasons.push(local("runs", index, "stack", `${stack.label} is not available: ${stack.reasons.join("; ") || "no reason given"}.`));
    }
    if (run.earlyStop && run.monitor !== "live") {
      reasons.push(local("runs", index, "early_stop", "Early stop needs the live monitor."));
    }
    if (run.repeats === null || run.repeats < 1) {
      reasons.push(local("runs", index, "repeats", "Repeats is at least 1."));
    }
    for (const group of stack?.groups ?? []) {
      const values = run.groups[group.key];
      if (values === undefined) {
        continue;
      }
      for (const parameter of group.parameters) {
        if (parameter.required && !isSet(values[parameter.key])) {
          reasons.push(local("runs", index, `stack.${group.key}.${parameter.key}`, `${parameter.key} is required when the group is set.`));
        }
      }
    }
    if (supportsEnvironment(stack).waves && run.waves) {
      for (const key of ["amplitude", "period", "steepness", "direction"]) {
        if (!isSet(run.waves[key])) {
          reasons.push(local("runs", index, `environment.waves.${key}`, `${key} is required when waves are set.`));
        }
      }
    }
  });
  if (draft.runs.length === 0) {
    reasons.push(local("runs", null, "runs", "Add at least one run."));
  }
  if (!draft.resources.fullUsage && draft.resources.nodes.length === 0) {
    reasons.push(local("resources", null, "nodes", "Choose at least one machine, or use every machine."));
  }
  if (draft.resources.labels.some((label) => label.key.trim().length === 0 && label.value.length > 0)) {
    reasons.push(local("resources", null, "required_labels", "A label value needs a name."));
  }
  return reasons;
}
