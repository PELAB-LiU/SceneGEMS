import { create } from "zustand";
import type { EvaluationData, GeneratedSceneData, SimulationFrame } from "../simulation/types";
import { hasExceededEvaluationTimeout, evaluationTimeBaseline } from "./evaluationTime";

export interface BatchRunResult {
  presetPath: string;
  label: string;
  requestId: string;
  status: "pending" | "running" | "success" | "error" | "timeout" | "cancelled";
  message?: string;
  evaluationData?: EvaluationData;
  evaluationTimeBaseline?: number;
  scene?: SimulationFrame;
}

const TERMINAL_STATUSES: BatchRunResult["status"][] = [
  "success",
  "error",
  "timeout",
  "cancelled",
];

interface BatchGenerationState {
  results: BatchRunResult[];
  selectedPaths: string[];
  running: boolean;
  batchTimeoutSeconds: number | null;
  batchRequestIds: Set<string>;
  setResults: (updater: BatchRunResult[] | ((prev: BatchRunResult[]) => BatchRunResult[])) => void;
  setSelectedPaths: (paths: string[]) => void;
  toggleSelectedPath: (path: string) => void;
  selectAllPaths: (paths: string[]) => void;
  clearSelectedPaths: () => void;
  setRunning: (running: boolean) => void;
  setBatchTimeoutSeconds: (seconds: number | null) => void;
  clearResults: () => void;
  registerBatchRequestIds: (requestIds: string[]) => void;
  clearBatchRequestIds: () => void;
  isBatchRequest: (requestId: string) => boolean;
  handleBatchGeneratedScene: (requestId: string, scene: GeneratedSceneData) => void;
  /** The status of one scene's cluster job; a scene that already ended keeps its status. */
  setBatchRequestStatus: (requestId: string, status: BatchRunResult["status"], message?: string) => void;
  markAllBatchStopped: () => void;
}

export const useBatchGenerationStore = create<BatchGenerationState>((set, get) => ({
  results: [],
  selectedPaths: [],
  running: false,
  batchTimeoutSeconds: null,
  batchRequestIds: new Set(),
  setResults: (updater) =>
    set((state) => ({
      results: typeof updater === "function" ? updater(state.results) : updater,
    })),
  setSelectedPaths: (paths) => set({ selectedPaths: paths }),
  toggleSelectedPath: (path) =>
    set((state) => {
      const selected = new Set(state.selectedPaths);
      if (selected.has(path)) selected.delete(path);
      else selected.add(path);
      return { selectedPaths: Array.from(selected) };
    }),
  selectAllPaths: (paths) => set({ selectedPaths: paths }),
  clearSelectedPaths: () => set({ selectedPaths: [] }),
  setRunning: (running) => set({ running }),
  setBatchTimeoutSeconds: (seconds) => set({ batchTimeoutSeconds: seconds }),
  clearResults: () => set({ results: [], batchRequestIds: new Set(), batchTimeoutSeconds: null }),
  registerBatchRequestIds: (requestIds) =>
    set({ batchRequestIds: new Set(requestIds) }),
  clearBatchRequestIds: () => set({ batchRequestIds: new Set() }),
  isBatchRequest: (requestId) => get().batchRequestIds.has(requestId),
  handleBatchGeneratedScene: (requestId, scene) =>
    set((state) => ({
      results: state.results.map((r) => {
        if (r.requestId !== requestId) return r;
        if (r.status === "cancelled" || r.status === "timeout") return r;

        if (scene.valid && scene.evaluationData) {
          return {
            ...r,
            status: "success",
            evaluationData: scene.evaluationData,
            scene: scene.scene,
            message: undefined,
          };
        }

        if (r.status === "success") return r;

        const evaluationData = scene.evaluationData ?? r.evaluationData;
        const baseline =
          r.evaluationTimeBaseline ??
          evaluationTimeBaseline(scene.evaluationData ?? r.evaluationData);
        const updated: BatchRunResult = {
          ...r,
          status: r.status === "pending" ? "running" : r.status,
          evaluationTimeBaseline: baseline,
          ...(scene.evaluationData ? { evaluationData: scene.evaluationData } : {}),
          ...(scene.scene ? { scene: scene.scene } : {}),
        };

        if (
          state.batchTimeoutSeconds !== null &&
          evaluationData &&
          hasExceededEvaluationTimeout(
            evaluationData,
            state.batchTimeoutSeconds,
            baseline
          )
        ) {
          return { ...updated, status: "timeout", message: undefined };
        }

        return updated;
      }),
    })),
  setBatchRequestStatus: (requestId, status, message) =>
    set((state) => ({
      results: state.results.map((r) =>
        r.requestId === requestId && !TERMINAL_STATUSES.includes(r.status) ? { ...r, status, message } : r
      ),
    })),
  markAllBatchStopped: () =>
    set((state) => ({
      running: false,
      results: state.results.map((r) =>
        r.status === "pending" || r.status === "running"
          ? { ...r, status: "cancelled", message: "Stopped" }
          : r
      ),
    })),
}));
