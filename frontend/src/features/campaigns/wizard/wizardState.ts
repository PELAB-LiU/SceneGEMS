import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

/**
 * The state of the create wizard. It holds what the operator entered, in plain JSON, and leaves
 * out everything the master derives: `configBuilder.ts` turns it into the campaign config, and the
 * stored draft survives a reload (one per browser).
 */

export const WIZARD_STEPS = ["scope", "domain", "trajectories", "runs", "resources", "policy", "review"] as const;
export type WizardStepId = (typeof WIZARD_STEPS)[number];

export const WIZARD_STEP_LABELS: Record<WizardStepId, string> = {
  scope: "Scope",
  domain: "Domain",
  trajectories: "Trajectories",
  runs: "Runs",
  resources: "Resources",
  policy: "Policy",
  review: "Review",
};

/** Values by parameter key; a key that is absent is left out of the config. */
export type ParamValues = Record<string, unknown>;

export interface ScopeEntryDraft {
  id: string;
  /** Class ids of the catalog. */
  classes: string[];
  /** Folder patterns (no slash) or class id patterns (with a slash), shell wildcards. */
  patterns: string[];
  quota: number | null;
  failureBudget: number | null;
}

export interface DomainDraft {
  /** False: the fields stay out of the config and the master's defaults apply. */
  custom: boolean;
  colregsConstants: string;
  vesselTypes: string;
  obstacleTypes: string;
  sceneGenerationTimeoutS: number | null;
  enforceLowTcpa: boolean;
}

export interface TrajectoriesDraft {
  generator: string;
  /** The generator's own parameters (search parameters, or the straight generator's timespan). */
  parameters: ParamValues;
  timeoutS: number | null;
}

export interface RunDraft {
  id: string;
  name: string;
  stackId: string;
  monitor: string;
  earlyStop: boolean;
  seed: number | null;
  repeats: number | null;
  /** Parameters of the stack itself (`dt`, `steps`). */
  stackParameters: ParamValues;
  /** Parameter groups by key; a group that is absent is left out and derived per scene. */
  groups: Record<string, ParamValues>;
  windVector: number[] | null;
  waves: ParamValues | null;
}

export interface ResourcesDraft {
  labels: { key: string; value: string }[];
  queueDepth: Record<string, number | null>;
  priority: number | null;
}

export type RetentionPolicy = "all" | "failures" | "verdicts_only";

export interface PolicyDraft {
  retention: RetentionPolicy;
  keepFrames: boolean;
  seed: number | null;
  maxCases: number | null;
  maxFailedVerdicts: number | null;
  maxDurationS: number | null;
}

export interface WizardDraft {
  name: string;
  description: string;
  scope: ScopeEntryDraft[];
  domain: DomainDraft;
  trajectories: TrajectoriesDraft;
  runs: RunDraft[];
  resources: ResourcesDraft;
  policy: PolicyDraft;
}

/** The queue depth stages and the config's defaults (`QueueDepthCaps`). */
export const QUEUE_DEPTH_DEFAULTS: Record<string, number> = {
  generate_scene: 16,
  generate_trajectories: 16,
  simulate: 32,
  monitor: 32,
  calibrate: 8,
};

export const QUEUE_DEPTH_LABELS: Record<string, string> = {
  generate_scene: "Scene generation",
  generate_trajectories: "Trajectory generation",
  simulate: "Simulation",
  monitor: "Monitoring",
  calibrate: "Calibration",
};

export const DEFAULT_SCENE_GENERATION_TIMEOUT_S = 60;
export const DEFAULT_TRAJECTORY_TIMEOUT_S = 1800;
export const DEFAULT_CAMPAIGN_SEED = 0;

let idCounter = 0;

/** An id for a list entry of the draft (stable while the entry exists). */
export function newEntryId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

export function emptyScopeEntry(): ScopeEntryDraft {
  return { id: newEntryId("scope"), classes: [], patterns: [], quota: 1, failureBudget: 0 };
}

export function emptyRun(stackId = "", monitor = "post_hoc"): RunDraft {
  return {
    id: newEntryId("run"),
    name: "",
    stackId,
    monitor,
    earlyStop: false,
    seed: null,
    repeats: 1,
    stackParameters: {},
    groups: {},
    windVector: null,
    waves: null,
  };
}

export function emptyDraft(): WizardDraft {
  return {
    name: "",
    description: "",
    scope: [emptyScopeEntry()],
    domain: {
      custom: false,
      colregsConstants: "",
      vesselTypes: "",
      obstacleTypes: "",
      sceneGenerationTimeoutS: DEFAULT_SCENE_GENERATION_TIMEOUT_S,
      enforceLowTcpa: false,
    },
    trajectories: { generator: "monitor_driven_rrt", parameters: {}, timeoutS: DEFAULT_TRAJECTORY_TIMEOUT_S },
    runs: [emptyRun()],
    resources: { labels: [], queueDepth: { ...QUEUE_DEPTH_DEFAULTS }, priority: 0 },
    policy: { retention: "all", keepFrames: false, seed: DEFAULT_CAMPAIGN_SEED, maxCases: null, maxFailedVerdicts: null, maxDurationS: null },
  };
}

export interface WizardState {
  step: WizardStepId;
  draft: WizardDraft;
  /** Steps the operator has left at least once (they show their problems in the stepper). */
  visited: WizardStepId[];
  setStep: (step: WizardStepId) => void;
  /** Applies a change to the draft; the function gets a copy it may change in place. */
  update: (change: (draft: WizardDraft) => void) => void;
  reset: () => void;
}

export const WIZARD_STORAGE_KEY = "scenegems:campaign-wizard";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** The persisted draft with every section present (a draft stored by an older build may lack newer fields). */
export function normalizeDraft(stored: unknown): WizardDraft {
  const base = emptyDraft();
  if (!stored || typeof stored !== "object") {
    return base;
  }
  const draft = stored as Partial<WizardDraft>;
  return {
    name: typeof draft.name === "string" ? draft.name : base.name,
    description: typeof draft.description === "string" ? draft.description : base.description,
    scope: Array.isArray(draft.scope) && draft.scope.length > 0 ? draft.scope : base.scope,
    domain: { ...base.domain, ...(draft.domain ?? {}) },
    trajectories: { ...base.trajectories, ...(draft.trajectories ?? {}) },
    runs: Array.isArray(draft.runs) && draft.runs.length > 0 ? draft.runs.map((run) => ({ ...emptyRun(), ...run })) : base.runs,
    resources: {
      ...base.resources,
      ...(draft.resources ?? {}),
      queueDepth: { ...base.resources.queueDepth, ...(draft.resources?.queueDepth ?? {}) },
    },
    policy: { ...base.policy, ...(draft.policy ?? {}) },
  };
}

/** The wizard store, kept per browser. Tests pass an in-memory storage. */
export function createWizardStore(storage?: StateStorage) {
  return create<WizardState>()(
    persist(
      (set) => ({
        step: "scope",
        draft: emptyDraft(),
        visited: [],
        setStep: (step) =>
          set((state) => ({ step, visited: state.visited.includes(state.step) ? state.visited : [...state.visited, state.step] })),
        update: (change) =>
          set((state) => {
            const draft = clone(state.draft);
            change(draft);
            return { draft };
          }),
        reset: () => set({ step: "scope", draft: emptyDraft(), visited: [] }),
      }),
      {
        name: WIZARD_STORAGE_KEY,
        version: 1,
        storage: createJSONStorage(() => storage ?? localStorage),
        partialize: (state) => ({ step: state.step, draft: state.draft, visited: state.visited }),
        merge: (persisted, current) => {
          const stored = (persisted ?? {}) as Partial<WizardState>;
          return {
            ...current,
            step: WIZARD_STEPS.includes(stored.step as WizardStepId) ? (stored.step as WizardStepId) : current.step,
            draft: normalizeDraft(stored.draft),
            visited: Array.isArray(stored.visited) ? stored.visited.filter((step) => WIZARD_STEPS.includes(step)) : [],
          };
        },
      }
    )
  );
}

export const useWizardStore = createWizardStore();
