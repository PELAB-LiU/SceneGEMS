import { Document, isSeq, visit, type YAMLSeq } from "yaml";
import type { CatalogGenerator, CatalogParameter, CatalogStack } from "../../../domain/cluster/campaignApi";
import { QUEUE_DEPTH_DEFAULTS, type ParamValues, type RunDraft, type WizardDraft } from "./wizardState";

/**
 * The wizard's draft as a campaign config (`campaign_config.CampaignConfig`): an object in the
 * config's key order, and the YAML text of it. Only what the operator set is written, plus the
 * fields the exit campaign states explicitly (repeats, monitor, priority, retention, seed);
 * everything else keeps the config model's defaults on the master.
 */

export type ConfigObject = Record<string, unknown>;

/** The catalog parts the builder needs. */
export interface BuilderCatalog {
  stacks: readonly CatalogStack[];
  generators: readonly CatalogGenerator[];
}

export const CONFIG_FORMAT = 1;

export function isSet(value: unknown): boolean {
  return value !== undefined && value !== null && value !== "";
}

function put(target: ConfigObject, key: string, value: unknown): void {
  if (isSet(value)) {
    target[key] = value;
  }
}

/** The values of a parameter set that are given (non-empty), in the order of the catalog's parameters, then any others. */
function givenValues(values: ParamValues, parameters: readonly CatalogParameter[]): ConfigObject {
  const result: ConfigObject = {};
  const known = new Set(parameters.map((parameter) => parameter.key));
  for (const parameter of parameters) {
    const value = values[parameter.key];
    if (isSet(value) && !(isMapValue(value) && Object.keys(value).length === 0)) {
      result[parameter.key] = value;
    }
  }
  for (const [key, value] of Object.entries(values)) {
    if (!known.has(key) && isSet(value)) {
      result[key] = value;
    }
  }
  return result;
}

function isMapValue(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function findStack(catalog: BuilderCatalog, stackId: string): CatalogStack | undefined {
  return catalog.stacks.find((stack) => stack.id === stackId);
}

export function findGenerator(catalog: BuilderCatalog, generatorId: string): CatalogGenerator | undefined {
  return catalog.generators.find((generator) => generator.id === generatorId);
}

function normalizeNewlines(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** Whether a stack lets a run set the wind or the waves (`environment` support is not `unsupported`). */
export function supportsEnvironment(stack: CatalogStack | undefined): { wind: boolean; waves: boolean } {
  return {
    wind: stack !== undefined && stack.environment.wind !== "unsupported",
    waves: stack !== undefined && stack.environment.waves !== "unsupported",
  };
}

function buildScope(draft: WizardDraft): ConfigObject[] {
  return draft.scope.map((entry) => {
    const item: ConfigObject = {};
    if (entry.classes.length > 0) {
      item.classes = [...entry.classes];
    }
    if (entry.patterns.length > 0) {
      item.patterns = [...entry.patterns];
    }
    put(item, "quota", entry.quota);
    put(item, "failure_budget", entry.failureBudget);
    return item;
  });
}

function buildDomain(draft: WizardDraft): ConfigObject {
  const domain: ConfigObject = {};
  if (draft.domain.custom) {
    domain.colregs_constants = normalizeNewlines(draft.domain.colregsConstants);
    domain.vessel_types = normalizeNewlines(draft.domain.vesselTypes);
    domain.obstacle_types = normalizeNewlines(draft.domain.obstacleTypes);
  }
  put(domain, "scene_generation_timeout_s", draft.domain.sceneGenerationTimeoutS);
  domain.enforce_low_tcpa = draft.domain.enforceLowTcpa;
  return domain;
}

function buildTrajectories(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const trajectories: ConfigObject = { generator: draft.trajectories.generator };
  const generator = findGenerator(catalog, draft.trajectories.generator);
  const parameters = generator?.parameters ?? [];
  const given = givenValues(draft.trajectories.parameters, parameters);
  if (generator?.params_field) {
    if (Object.keys(given).length > 0) {
      trajectories[generator.params_field] = given;
    }
  } else {
    Object.assign(trajectories, given);
  }
  put(trajectories, "timeout_s", draft.trajectories.timeoutS);
  return trajectories;
}

function buildStack(run: RunDraft, stack: CatalogStack | undefined): ConfigObject {
  const result: ConfigObject = { simulation_layer: stack?.simulation_layer ?? "kinematic" };
  if (stack) {
    result.mode = stack.mode;
  }
  Object.assign(result, givenValues(run.stackParameters, stack?.parameters ?? []));
  for (const group of stack?.groups ?? []) {
    const values = run.groups[group.key];
    if (values !== undefined) {
      result[group.key] = givenValues(values, group.parameters);
    }
  }
  return result;
}

function buildRun(run: RunDraft, catalog: BuilderCatalog): ConfigObject {
  const stack = findStack(catalog, run.stackId);
  const result: ConfigObject = {};
  put(result, "name", run.name.trim());
  result.stack = buildStack(run, stack);
  const environment: ConfigObject = {};
  const support = supportsEnvironment(stack);
  if (support.wind && run.windVector && run.windVector.length === 3) {
    environment.wind_vector = [...run.windVector];
  }
  if (support.waves && run.waves) {
    environment.waves = { ...run.waves };
  }
  if (Object.keys(environment).length > 0) {
    result.environment = environment;
  }
  put(result, "seed", run.seed);
  result.repeats = run.repeats ?? 1;
  result.monitor = run.monitor;
  if (run.earlyStop) {
    result.early_stop = true;
  }
  return result;
}

function buildResources(draft: WizardDraft): ConfigObject {
  const resources: ConfigObject = {};
  const labels: Record<string, string> = {};
  for (const { key, value } of draft.resources.labels) {
    if (key.trim()) {
      labels[key.trim()] = value;
    }
  }
  if (Object.keys(labels).length > 0) {
    resources.required_labels = labels;
  }
  const queueDepth: Record<string, number> = {};
  for (const [stage, defaultDepth] of Object.entries(QUEUE_DEPTH_DEFAULTS)) {
    const depth = draft.resources.queueDepth[stage];
    if (depth !== null && depth !== undefined && depth !== defaultDepth) {
      queueDepth[stage] = depth;
    }
  }
  if (Object.keys(queueDepth).length > 0) {
    resources.queue_depth = queueDepth;
  }
  resources.priority = draft.resources.priority ?? 0;
  return resources;
}

function buildPolicy(draft: WizardDraft): ConfigObject {
  const policy: ConfigObject = {
    retention: draft.policy.retention,
    keep_frames: draft.policy.keepFrames,
    seed: draft.policy.seed ?? 0,
  };
  const stop: ConfigObject = {};
  put(stop, "max_cases", draft.policy.maxCases);
  put(stop, "max_failed_verdicts", draft.policy.maxFailedVerdicts);
  put(stop, "max_duration_s", draft.policy.maxDurationS);
  if (Object.keys(stop).length > 0) {
    policy.stop = stop;
  }
  return policy;
}

/** The config the draft describes. A run with an unknown stack gets the layer only; `checkDraft` reports it. */
export function buildCampaignConfig(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const config: ConfigObject = { format: CONFIG_FORMAT, name: draft.name.trim() };
  put(config, "description", draft.description.trim());
  config.scope = buildScope(draft);
  config.domain = buildDomain(draft);
  config.trajectories = buildTrajectories(draft, catalog);
  config.execution = { runs: draft.runs.map((run) => buildRun(run, catalog)) };
  config.resources = buildResources(draft);
  config.policy = buildPolicy(draft);
  return config;
}

/** The YAML text of a config: lists of numbers inline, long text as block scalars, nothing folded. */
export function configToYaml(config: ConfigObject): string {
  const document = new Document(config);
  visit(document, {
    Seq(_key, seq: YAMLSeq) {
      if (seq.items.length > 0 && seq.items.every((item) => !isSeq(item) && typeof (item as { value?: unknown }).value === "number")) {
        seq.flow = true;
      }
    },
  });
  return document.toString({ lineWidth: 0, indent: 2, flowCollectionPadding: false });
}

export function buildCampaignYaml(draft: WizardDraft, catalog: BuilderCatalog): string {
  return configToYaml(buildCampaignConfig(draft, catalog));
}
