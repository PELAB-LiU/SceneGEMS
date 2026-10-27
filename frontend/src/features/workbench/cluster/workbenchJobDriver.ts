import { jobFailureMessage, readResultField, type JobProgressEvent } from "../../../domain/cluster/clusterJobs";
import { instanceTopic, jobInstanceName } from "../../../domain/cluster/liveProtocol";
import { INSTANCE_FRAMES_KEPT, instanceReducer, type InstanceTopicState, type SceneSample, type TrajectoryPreview } from "../../../domain/cluster/liveTopics";
import { LiveTopicWatcher } from "../../../domain/cluster/liveTopicWatcher";
import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { JobView } from "../../../domain/cluster/schemas";
import { FrameBuffer } from "../../observe/observeFrames";
import { useClusterRunStore } from "./clusterRunStore";

import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { isFullTrajectoryScenario, parseScenarioFile } from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import { parseFrame, type ParsedServerMessage } from "../../../domain/simulation/protocol";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import type { TrajectoryGenerationParamsWire } from "../../../domain/simulation/wireTypes";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { useUiStore } from "../../../app/uiStore";
import type { JobTypeResources } from "./workbenchResources";
import {
  MONITORING_JOB,
  monitoredFrames,
  monitoringSubmission,
  poolRequestId,
  runClusterJob,
  SCENE_GENERATION_JOB,
  sceneGenerationSubmission,
  sceneJobResult,
  singleSceneTrajectories,
  TRAJECTORY_GENERATION_JOB,
  trajectoryGenerationSubmission,
  trajectoryJobResult,
  watchPoolPreviews,
  type PoolKind,
  type SceneGenerationInput,
  type WorkbenchCluster,
} from "./workbenchJobs";

/**
 * Runs the workbench's generation and monitoring as jobs on the active cluster and reports
 * them through the messages the workbench's stores already understand (`generated_scene`,
 * `trajectory_generation_preview`, `trajectory_generation_result`), so the scene and
 * trajectory pages read the same state whether a job is queued, running or done.
 */

export interface ClusterAccess {
  cluster: WorkbenchCluster | null;
  resources: (jobType: string) => JobTypeResources;
}

export type SceneJobOutcome =
  | {
      ok: true;
      valid: boolean;
      scene: SimulationFrame;
      /** The scene's metadata as the workbench keeps it (without the scene). */
      evaluationData: EvaluationData;
      /** The job's EvaluationData as a scenario file holds it, with `best_scene`. */
      scenario: Record<string, unknown>;
    }
  | { ok: false; message: string; stopped: boolean };

const STOPPED_MESSAGE = "Scene generation stopped.";

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

const NO_CLUSTER: ClusterAccess = {
  cluster: null,
  resources: (jobType) => ({ jobType, nodes: 0, slots: 0, freeSlots: 0, blocker: "No cluster is selected." }),
};

export class WorkbenchJobDriver {
  private access: () => ClusterAccess;
  private dispatch: (message: ParsedServerMessage) => void;
  private readonly sceneJobs = new Map<string, AbortController>();
  private trajectoryJob: AbortController | null = null;
  private previewMonitorJob: AbortController | null = null;
  private simulationJob: AbortController | null = null;
  private simulationWatcher: LiveTopicWatcher<InstanceTopicState> | null = null;

  constructor(access: () => ClusterAccess = () => NO_CLUSTER, dispatch: (message: ParsedServerMessage) => void = () => undefined) {
    this.access = access;
    this.dispatch = dispatch;
  }

  /** The cluster jobs go to from now on (the active cluster as the workbench sees it). */
  setCluster(access: ClusterAccess): void {
    this.access = () => access;
  }

  /** Where job reports go from now on. */
  setDispatch(dispatch: (message: ParsedServerMessage) => void): void {
    this.dispatch = dispatch;
  }

  /** Why the active cluster cannot run a job type now, null when it can. */
  blocker(jobType: string): string | null {
    const { cluster, resources } = this.access();
    return cluster === null ? resources(jobType).blocker ?? "No cluster is selected." : resources(jobType).blocker;
  }

  /** One scene, shown on the scene page as it arrives; monitored on the cluster when a node offers monitoring. */
  async generateScene(requestId: string, input: SceneGenerationInput): Promise<SceneJobOutcome> {
    const playback = usePlaybackStore.getState();
    playback.setActiveSceneGenerationRequestId(requestId);
    const outcome = await this.runScene(requestId, input, false);
    if (usePlaybackStore.getState().activeSceneGenerationRequestId === requestId) {
      usePlaybackStore.getState().setActiveSceneGenerationRequestId(null);
    }
    if (outcome.ok && outcome.valid) {
      void this.monitorScene(requestId, outcome.scenario, input.colregsConstraintsContent);
    }
    return outcome;
  }

  /** One scene of a batch: its row follows the job (queued, running, done). Resolves when the job ended. */
  async generateBatchScene(requestId: string, input: SceneGenerationInput): Promise<void> {
    const batch = useBatchGenerationStore.getState();
    const outcome = await this.runScene(requestId, input, true);
    if (outcome.ok) {
      if (!outcome.valid) {
        batch.setBatchRequestStatus(requestId, "timeout", "No valid scene within the timeout.");
      }
      return;
    }
    batch.setBatchRequestStatus(requestId, outcome.stopped ? "cancelled" : "error", outcome.stopped ? "Stopped" : outcome.message);
  }

  stopScenes(): void {
    for (const controller of this.sceneJobs.values()) {
      controller.abort();
    }
    this.sceneJobs.clear();
  }

  get runningScenes(): number {
    return this.sceneJobs.size;
  }

  private async runScene(requestId: string, input: SceneGenerationInput, batch: boolean): Promise<SceneJobOutcome> {
    const blocker = this.blocker(SCENE_GENERATION_JOB);
    const cluster = this.access().cluster;
    if (blocker !== null || cluster === null) {
      return { ok: false, message: blocker ?? "No cluster is selected.", stopped: false };
    }
    const controller = new AbortController();
    this.sceneJobs.set(requestId, controller);
    const previews = new PreviewFollower(cluster, "scene_generation", (preview) => this.dispatchSample(requestId, preview as SceneSample));
    try {
      const job = await runClusterJob(cluster, sceneGenerationSubmission(input), {
        signal: controller.signal,
        onProgress: (event) => {
          if (batch) {
            useBatchGenerationStore.getState().setBatchRequestStatus(requestId, event.job.state === "running" ? "running" : "pending");
          }
          previews.follow(event, useUiStore.getState().sceneGenerationLivePreview);
        },
      });
      previews.stop();
      if (job.state !== "succeeded") {
        return { ok: false, message: jobFailureMessage(job), stopped: job.state === "cancelled" };
      }
      const result = await sceneJobResult(cluster, job, controller.signal);
      const parsed = parseScenarioFile(JSON.stringify(result.evaluationData));
      this.dispatch({ kind: "generated_scene", requestId, valid: result.valid, scene: parsed.scene, evaluationData: parsed.evaluationData });
      return { ok: true, valid: result.valid, scene: parsed.scene, evaluationData: parsed.evaluationData, scenario: result.evaluationData };
    } catch (error) {
      if (isAbort(error) || controller.signal.aborted) {
        return { ok: false, message: STOPPED_MESSAGE, stopped: true };
      }
      return { ok: false, message: `Scene generation on the cluster failed: ${describe(error)}`, stopped: false };
    } finally {
      previews.stop();
      if (this.sceneJobs.get(requestId) === controller) {
        this.sceneJobs.delete(requestId);
      }
    }
  }

  /** A search sample while the job runs: progress only, so it never ends the request early. */
  private dispatchSample(requestId: string, sample: SceneSample): void {
    if (sample.final || sample.scene === undefined || sample.scene === null) {
      return;
    }
    try {
      const evaluationData = typeof sample.evaluation_data === "object" && sample.evaluation_data !== null ? (sample.evaluation_data as EvaluationData) : null;
      this.dispatch({ kind: "generated_scene", requestId, valid: false, scene: parseFrame(sample.scene), evaluationData });
    } catch {
      // A sample that does not parse is only a missed preview.
    }
  }

  /**
   * Monitors one scene with the cluster's post-hoc monitor and merges the verdicts into the shown
   * scene. Without a node that monitors, the scene stays as it is.
   */
  async monitorScene(requestId: string, scenario: Record<string, unknown>, colregsConstraintsContent: string): Promise<void> {
    const cluster = this.access().cluster;
    if (cluster === null || this.blocker(MONITORING_JOB) !== null) {
      return;
    }
    const trajectories = singleSceneTrajectories(scenario);
    if (trajectories === null) {
      return;
    }
    usePlaybackStore.getState().beginSceneMonitor(requestId);
    try {
      const job = await runClusterJob(cluster, monitoringSubmission(trajectories, colregsConstraintsContent, requestId));
      if (job.state === "succeeded") {
        const frames = await monitoredFrames(cluster, job);
        if (frames[0]) {
          usePlaybackStore.getState().applySceneMonitorResult(requestId, frames[0]);
        }
      }
    } catch {
      // The scene stays unmonitored, as with no node that monitors.
    }
  }

  /**
   * Monitors the loaded preview trajectory on the cluster and replaces the preview's frames with
   * the monitored ones, while the same scenario is still loaded.
   */
  async monitorPreview(scenarioId: string, scenarioContent: string, colregsConstraintsContent: string): Promise<void> {
    this.previewMonitorJob?.abort();
    const playback = usePlaybackStore.getState();
    let raw: unknown;
    try {
      raw = JSON.parse(scenarioContent);
    } catch {
      return;
    }
    if (!isFullTrajectoryScenario(raw)) {
      playback.setPreviewMonitor({ status: "idle", scenarioId, message: null });
      return;
    }
    const cluster = this.access().cluster;
    const blocker = this.blocker(MONITORING_JOB);
    if (cluster === null || blocker !== null) {
      playback.setPreviewMonitor({ status: "unavailable", scenarioId, message: blocker });
      return;
    }
    const controller = new AbortController();
    this.previewMonitorJob = controller;
    const trajectories = (raw as { trajectories: Record<string, unknown> }).trajectories;
    playback.setPreviewMonitor({ status: "running", scenarioId, message: "Monitoring the trajectory on the cluster..." });
    const stillLoaded = () => usePlaybackStore.getState().activeScenarioId === scenarioId && !controller.signal.aborted;
    try {
      const job = await runClusterJob(cluster, monitoringSubmission(trajectories, colregsConstraintsContent, scenarioId), { signal: controller.signal });
      if (!stillLoaded()) {
        return;
      }
      if (job.state !== "succeeded") {
        usePlaybackStore.getState().setPreviewMonitor({ status: "failed", scenarioId, message: jobFailureMessage(job) });
        return;
      }
      const frames = await monitoredFrames(cluster, job, controller.signal);
      if (!stillLoaded()) {
        return;
      }
      usePlaybackStore.getState().setTrajectoryPreviewFrames(frames);
      usePlaybackStore.getState().setPreviewMonitor({ status: "done", scenarioId, message: null });
    } catch (error) {
      if (stillLoaded()) {
        usePlaybackStore.getState().setPreviewMonitor({ status: "failed", scenarioId, message: describe(error) });
      }
    } finally {
      if (this.previewMonitorJob === controller) {
        this.previewMonitorJob = null;
      }
    }
  }

  /** Plans trajectories for a scene; the trajectory page follows the previews and the result. */
  async generateTrajectories(requestId: string, scenarioContent: string, colregsConstraintsContent: string, params: TrajectoryGenerationParamsWire): Promise<void> {
    this.trajectoryJob?.abort();
    usePlaybackStore.getState().clearPreviewFrames();
    useTrajectoryGenerationStore.getState().startRun(requestId);
    const cluster = this.access().cluster;
    const blocker = this.blocker(TRAJECTORY_GENERATION_JOB);
    if (cluster === null || blocker !== null) {
      this.dispatchTrajectoryResult(requestId, blocker ?? "No cluster is selected.");
      return;
    }
    const controller = new AbortController();
    this.trajectoryJob = controller;
    const previews = new PreviewFollower(cluster, "trajectory_generation", (preview) =>
      this.dispatch({ kind: "trajectory_generation_preview", requestId, trajectoryData: (preview as TrajectoryPreview).trajectories as Record<string, unknown> })
    );
    try {
      const job = await runClusterJob(cluster, trajectoryGenerationSubmission({ scenarioContent, colregsConstraintsContent, params }), {
        signal: controller.signal,
        onProgress: (event) => previews.follow(event, true),
      });
      previews.stop();
      if (job.state === "cancelled") {
        useTrajectoryGenerationStore.getState().markStopped();
        return;
      }
      if (job.state !== "succeeded") {
        this.dispatchTrajectoryResult(requestId, jobFailureMessage(job));
        return;
      }
      const result = await trajectoryJobResult(cluster, job, controller.signal);
      this.dispatch({ kind: "trajectory_generation_result", requestId, ...result });
    } catch (error) {
      if (isAbort(error) || controller.signal.aborted) {
        useTrajectoryGenerationStore.getState().markStopped();
        return;
      }
      this.dispatchTrajectoryResult(requestId, `Trajectory generation on the cluster failed: ${describe(error)}`);
    } finally {
      previews.stop();
      if (this.trajectoryJob === controller) {
        this.trajectoryJob = null;
      }
    }
  }

  stopTrajectories(): void {
    this.trajectoryJob?.abort();
    this.trajectoryJob = null;
    useTrajectoryGenerationStore.getState().markStopped();
  }

  /**
   * Runs a simulation as one job and shows its frames in the simulation stream as the node
   * sends them, paced to the run store's speed. A kinematic run may end before the observation
   * reaches its node; its frames then come from the cluster's monitor over the run's result.
   */
  async runSimulation(submission: JobSubmission, colregsConstraintsContent: string): Promise<void> {
    this.simulationJob?.abort();
    const run = useClusterRunStore.getState();
    const cluster = this.access().cluster;
    const blocker = this.blocker(submission.job_type);
    if (cluster === null || blocker !== null) {
      run.update({ status: "failed", jobId: null, nodeId: null, message: blocker ?? "No cluster is selected." });
      return;
    }
    const controller = new AbortController();
    this.simulationJob = controller;
    usePlaybackStore.getState().clearSimulationTrajectories();
    run.update({ status: "queued", jobId: null, nodeId: null, message: "Waiting for a free slot on the cluster..." });
    const frames = new FrameBuffer(INSTANCE_FRAMES_KEPT);
    let watchedKey: string | null = null;
    let unwatch: () => void = () => {};
    const stopWatching = () => {
      unwatch();
      unwatch = () => {};
      this.simulationWatcher = null;
    };
    const current = () => this.simulationJob === controller;
    try {
      const job = await runClusterJob(cluster, submission, {
        signal: controller.signal,
        onProgress: ({ job, status }) => {
          if (!current()) {
            return;
          }
          const running = job.state === "leased" || job.state === "running";
          useClusterRunStore.getState().update({
            jobId: job.job_id,
            nodeId: job.lease_owner,
            ...(job.state === "queued" ? { status: "queued" } : running ? { status: "running", message: status?.message ?? "Running on the cluster" } : {}),
          });
          const key = running && job.lease_owner ? `${job.lease_owner}/${jobInstanceName(job.job_id, job.attempt)}` : null;
          if (key === null || key === watchedKey || cluster.channel === null) {
            return;
          }
          stopWatching();
          watchedKey = key;
          const watcher = new LiveTopicWatcher(cluster.channel, instanceTopic(job.lease_owner as string, jobInstanceName(job.job_id, job.attempt)), instanceReducer, {
            speed: useClusterRunStore.getState().speed,
          });
          this.simulationWatcher = watcher;
          unwatch = watcher.subscribe(() => {
            const data = watcher.getState().data;
            if (data && current()) {
              usePlaybackStore.getState().applyMergedSimulationFrames(frames.sync(data.frames, data.frameCount));
            }
          });
        },
      });
      stopWatching();
      if (!current()) {
        return;
      }
      if (job.state !== "succeeded") {
        useClusterRunStore.getState().update({ status: job.state === "cancelled" ? "stopped" : "failed", message: jobFailureMessage(job) });
        return;
      }
      const result = typeof job.result === "object" && job.result !== null ? (job.result as Record<string, unknown>) : {};
      const trajectories = await readResultField(cluster.client, result.trajectories, { signal: controller.signal });
      const planned = typeof trajectories === "object" && trajectories !== null ? ((trajectories as { scene_list?: unknown[] }).scene_list?.length ?? 0) : 0;
      const shown = usePlaybackStore.getState().simulationFrames.length;
      if (planned > shown && typeof trajectories === "object" && trajectories !== null && this.blocker(MONITORING_JOB) === null) {
        useClusterRunStore.getState().update({ status: "finishing", message: "The run ended before it was watched: monitoring its result on the cluster..." });
        const monitorJob = await runClusterJob(cluster, monitoringSubmission(trajectories as Record<string, unknown>, colregsConstraintsContent, job.job_id), { signal: controller.signal });
        if (monitorJob.state === "succeeded" && current()) {
          usePlaybackStore.getState().applyMergedSimulationFrames(await monitoredFrames(cluster, monitorJob, controller.signal));
        }
      }
      if (current()) {
        useClusterRunStore.getState().update({ status: "done", message: `Finished: ${usePlaybackStore.getState().simulationFrames.length} frames.` });
      }
    } catch (error) {
      if (current()) {
        const stopped = isAbort(error) || controller.signal.aborted;
        useClusterRunStore.getState().update({ status: stopped ? "stopped" : "failed", message: stopped ? "Stopped." : `The run on the cluster failed: ${describe(error)}` });
      }
    } finally {
      stopWatching();
      if (this.simulationJob === controller) {
        this.simulationJob = null;
      }
    }
  }

  /** Changes the pace the running simulation is watched (and, for a kinematic run, run) at. */
  setSimulationSpeed(speed: number): void {
    useClusterRunStore.getState().update({ speed });
    this.simulationWatcher?.configure({ speed });
  }

  stopSimulation(): void {
    if (this.simulationJob !== null) {
      this.simulationJob.abort();
      useClusterRunStore.getState().update({ status: "stopped", message: "Stopped." });
    }
    this.simulationJob = null;
  }

  /** Stops everything this driver follows (the workbench is closed or switched to another cluster). */
  stopAll(): void {
    this.stopScenes();
    this.trajectoryJob?.abort();
    this.previewMonitorJob?.abort();
    this.stopSimulation();
  }

  private dispatchTrajectoryResult(requestId: string, errorMessage: string): void {
    this.dispatch({ kind: "trajectory_generation_result", requestId, trajectoryData: null, valid: false, complete: null, errorMessage });
  }
}

/** Follows the previews of a job on the pool of whichever node holds it, switching nodes on a retry. */
class PreviewFollower {
  private readonly cluster: WorkbenchCluster;
  private readonly kind: PoolKind;
  private readonly onPreview: (preview: SceneSample | TrajectoryPreview) => void;
  private watched: string | null = null;
  private unwatch: () => void = () => {};

  constructor(cluster: WorkbenchCluster, kind: PoolKind, onPreview: (preview: SceneSample | TrajectoryPreview) => void) {
    this.cluster = cluster;
    this.kind = kind;
    this.onPreview = onPreview;
  }

  follow({ job }: JobProgressEvent, wanted: boolean): void {
    const key = previewKey(job);
    if (!wanted || this.cluster.channel === null || key === null) {
      if (!wanted || key === null) {
        this.stop();
      }
      return;
    }
    if (key === this.watched) {
      return;
    }
    this.stop();
    this.watched = key;
    this.unwatch = watchPoolPreviews(this.cluster.channel, job.lease_owner as string, this.kind, poolRequestId(job), this.onPreview);
  }

  stop(): void {
    this.unwatch();
    this.unwatch = () => {};
    this.watched = null;
  }
}

function previewKey(job: JobView): string | null {
  if ((job.state !== "leased" && job.state !== "running") || !job.lease_owner) {
    return null;
  }
  return `${job.lease_owner}/${poolRequestId(job)}`;
}
