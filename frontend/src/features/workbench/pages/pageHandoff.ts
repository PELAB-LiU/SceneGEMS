import type { OutputRow } from "../../../domain/cluster/historyApi";
import type { CampaignRow, CampaignStep } from "../../../domain/cluster/schemas";
import { useScenePlaybackStore } from "../../../domain/playback/playbackStore";
import { parseScenarioFile } from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import type { GeneratedSceneData } from "../../../domain/simulation/types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { configRef } from "./entryConfig";
import { trajectoryScenarioOf } from "./entryLoader";
import { inputFromPreviousPage, useScenePageStore, useTrajectoryPageStore, useSimulationPageStore, type PageInput } from "./pageStore";

/**
 * Setting a page's input in one click: from the previous page's output, from an output in
 * Campaign History, or from a file. The trajectory page keeps its input scene in the trajectory
 * generation store (it draws it before anything is planned); the simulation page loads its input
 * trajectories into the gateway session and the cluster run (`useSimulationWorkflow`).
 */

export const PREVIOUS_OUTPUT_LABEL = {
  trajectoryGeneration: "The scene of the Scene Generation page",
  simulation: "The trajectories of the Trajectory Generation page",
} as const;

/** The scene the scene page shows, as the trajectory page's input; null when it shows no valid scene. */
export function sceneOfScenePage(sourceName: string | null): { input: PageInput; scene: GeneratedSceneData } | null {
  const shown = useScenePlaybackStore.getState().latestGeneratedScene;
  if (!shown?.valid || !shown.evaluationData) {
    return null;
  }
  const fromEntry = inputFromPreviousPage(useScenePageStore.getState().output);
  const label = sourceName ? `${PREVIOUS_OUTPUT_LABEL.trajectoryGeneration} (${sourceName})` : PREVIOUS_OUTPUT_LABEL.trajectoryGeneration;
  return {
    input: fromEntry ?? { label, origin: "previous_page", ref: null, source: { file: sourceName ?? "scene_generation.json" } },
    scene: { scene: shown.scene, evaluationData: shown.evaluationData, valid: true },
  };
}

/** Sets the trajectory page's input scene. */
export function setTrajectoryInput(input: PageInput, scene: GeneratedSceneData): void {
  useTrajectoryGenerationStore.getState().setHandoffScene(scene, input.origin === "file" ? input.label : null);
  useTrajectoryPageStore.getState().setInput(input);
}

/** The trajectories the trajectory page shows, as the simulation page's input; null when it shows none usable. */
export function trajectoriesOfTrajectoryPage(): { input: PageInput; content: string } | null {
  const store = useTrajectoryGenerationStore.getState();
  if (!store.resultValid || store.resultScenarioJson === null) {
    return null;
  }
  const fromEntry = inputFromPreviousPage(useTrajectoryPageStore.getState().output);
  return {
    input: fromEntry ?? { label: PREVIOUS_OUTPUT_LABEL.simulation, origin: "previous_page", ref: null, source: { file: "planned_trajectory.json" } },
    content: store.resultScenarioJson,
  };
}

/** Whether an entry ran a step; a campaign from before Phase 6 ran the whole chain. */
export function entryRanStep(row: Pick<CampaignRow, "steps">, step: CampaignStep): boolean {
  return row.steps === undefined || row.steps === null || row.steps.includes(step);
}

/** A history output as a page's input: its artifact and where it came from. */
export function inputOfHistoryOutput(entry: Pick<CampaignRow, "campaign_id" | "name">, row: OutputRow, step: CampaignStep): PageInput | null {
  if (row.artifact === null) {
    return null;
  }
  return {
    label: `${entry.name}, case ${row.case_index + 1}${row.run_index !== null ? `, run ${row.run_index + 1}` : ""}`,
    origin: "history",
    ref: configRef(row.artifact),
    source: { campaign_id: entry.campaign_id, case_id: row.case_id, step },
  };
}

/** A file as a page's input. */
export function inputOfFile(fileName: string): PageInput {
  return { label: fileName, origin: "file", ref: null, source: { file: fileName } };
}

/** A scene document (a file or a history output) as the trajectory page shows it. */
export function sceneOfDocument(document: unknown): GeneratedSceneData {
  const { scene, evaluationData } = parseScenarioFile(JSON.stringify(document));
  return { scene, evaluationData, valid: true };
}

/** A trajectory document (a file or a history output) as the simulation page loads it; null when it holds no trajectories. */
export function trajectoryContentOfDocument(document: unknown): string | null {
  const scenario = trajectoryScenarioOf(document);
  return scenario === null ? null : JSON.stringify(scenario);
}

/** On the simulation page the input and the run share the canvas and the session: a new input replaces the shown run. */
export function forgetSimulationRun(): void {
  useSimulationPageStore.getState().setLocalOutput(null);
}
