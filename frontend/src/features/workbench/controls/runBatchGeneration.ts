import { formatFunctionalPresetLabel } from "./functionalPresetPaths";
import { loadFunctionalPresetsManifest } from "./functionalPresets";
import {
  useBatchGenerationStore,
  type BatchRunResult,
} from "../../../domain/sceneGeneration/batchGenerationStore";

export interface RunBatchGenerationParams {
  selectedPaths: string[];
  loadPresetText: (path: string) => Promise<string>;
  /** Runs every row as one batch entry with a case per scenario; resolves once every row ended. */
  generateBatch: (rows: { requestId: string; label: string; specText: string }[]) => Promise<void>;
  sceneGenerationTimeoutSeconds: number;
  /** Returns true if generation has been stopped externally (e.g. shared Stop button). */
  isAborted: () => boolean;
}

/**
 * Runs every selected preset as one workbench entry with a case per scenario (design doc 6.3),
 * so the cluster runs as many as it has free slots and queues the rest. Each row follows its
 * case's job (queued, running, done); the per-scene timeout is the generation's own, not the wait
 * in the queue.
 */
export async function runBatchGeneration({
  selectedPaths,
  loadPresetText,
  generateBatch,
  sceneGenerationTimeoutSeconds,
  isAborted,
}: RunBatchGenerationParams): Promise<void> {
  if (selectedPaths.length === 0) {
    return;
  }
  const paths = [...selectedPaths];
  useBatchGenerationStore.getState().setRunning(true);

  try {
    const labelByPath = new Map<string, string>();
    try {
      const manifest = await loadFunctionalPresetsManifest();
      for (const preset of manifest.presets) {
        labelByPath.set(preset.path, preset.label);
      }
    } catch {
      // Fall back to path-derived labels.
    }

    const jobs = await Promise.all(
      paths.map(async (path) => ({
        presetPath: path,
        label: labelByPath.get(path) ?? formatFunctionalPresetLabel(path),
        requestId: crypto.randomUUID(),
        specText: await loadPresetText(path),
      }))
    );

    const initial: BatchRunResult[] = jobs.map((job) => ({
      presetPath: job.presetPath,
      label: job.label,
      requestId: job.requestId,
      status: "pending",
    }));
    useBatchGenerationStore.getState().setResults(initial);
    useBatchGenerationStore.getState().registerBatchRequestIds(jobs.map((j) => j.requestId));
    useBatchGenerationStore.getState().setBatchTimeoutSeconds(sceneGenerationTimeoutSeconds);

    if (isAborted()) {
      useBatchGenerationStore.getState().markAllBatchStopped();
      return;
    }

    await generateBatch(jobs.map((job) => ({ requestId: job.requestId, label: job.label, specText: job.specText })));
  } catch (error) {
    useBatchGenerationStore.getState().setResults((prev) =>
      prev.map((r) =>
        r.status === "pending" || r.status === "running"
          ? {
              ...r,
              status: "error",
              message: error instanceof Error ? error.message : "Batch failed",
            }
          : r
      )
    );
  } finally {
    useBatchGenerationStore.getState().clearBatchRequestIds();
    useBatchGenerationStore.getState().setBatchTimeoutSeconds(null);
    useBatchGenerationStore.getState().setRunning(false);
  }
}
