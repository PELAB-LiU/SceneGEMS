import { useCallback, useEffect, useRef, useState } from "react";
import { usePlaybackStore } from "../playback/playbackStore";
import { BackendWsClient } from "./wsClient";
import type { ParsedServerMessage } from "./protocol";
import { gatewayWsUrl } from "./simulationConfig";
import type { SimulationFrame } from "./types";
import type { ClientToServerMessage } from "./wireTypes";
import { useUiStore } from "../../app/uiStore";
import {
  mergeFramesInWorker,
  shouldMergeFramesInWorker,
} from "../playback/mergeFramesInWorker";
import { useRecordingStore } from "../playback/recordingStore";
import { useBatchGenerationStore } from "../sceneGeneration/batchGenerationStore";
import { buildFramesFromTrajectoryData } from "../sceneGeneration/parseEvaluationDataFile";
import { useTrajectoryGenerationStore } from "../trajectoryGeneration/trajectoryGenerationStore";
import { useConnectionStore } from "../../features/workbench/connection/connectionStore";
import { useWorkbenchCluster } from "../../features/workbench/cluster/useWorkbenchCluster";
import { WorkbenchJobDriver } from "../../features/workbench/cluster/workbenchJobDriver";
import type { SceneGenerationInput } from "../../features/workbench/cluster/workbenchJobs";
import { kinematicSimulationSubmission, type SimulationRunPlan } from "../../features/workbench/cluster/simulationJobs";
import { isFullTrajectoryScenario } from "../sceneGeneration/parseEvaluationDataFile";
import type { TrajectoryGenerationParamsWire } from "./wireTypes";
import { missingTrajectoriesReason, NO_TRAJECTORIES_MESSAGE } from "./trajectoryGuard";

let previewTrajectoryChunkQueue = Promise.resolve();
let simulationTrajectoryChunkQueue = Promise.resolve();
let simulationModelsToken = 0;

function enqueuePreviewTrajectoryChunk(task: () => Promise<void>): void {
  previewTrajectoryChunkQueue = previewTrajectoryChunkQueue.then(task, task);
}

function enqueueSimulationTrajectoryChunk(task: () => Promise<void>): void {
  simulationTrajectoryChunkQueue = simulationTrajectoryChunkQueue.then(task, task);
}

function trajectoryChunkMatchesActiveScenario(
  activeScenarioId: string | null,
  chunkScenarioId: string | null
): boolean {
  if (activeScenarioId === null && chunkScenarioId === null) {
    return true;
  }
  if (activeScenarioId === null || chunkScenarioId === null) {
    return false;
  }
  return activeScenarioId === chunkScenarioId;
}

export interface LoadScenarioOptions {
  /** COLREGS constants for the cluster's monitoring of the loaded trajectory; the trajectory stays unmonitored without them. */
  colregsConstraintsContent?: string;
}

/**
 * The workbench's backend: scene generation, trajectory generation and monitoring run as jobs
 * on the active cluster (`WorkbenchJobDriver`); the interactive simulation runs through the
 * gateway WebSocket of the same cluster's master, over the MQTT broker of the Connections page.
 */
export function useSimulationWorkflow() {
  const ingestFrames = usePlaybackStore((s) => s.ingestFrames);
  const applyMergedPreviewFrames = usePlaybackStore((s) => s.applyMergedPreviewFrames);
  const ingestSimulationFrames = usePlaybackStore((s) => s.ingestSimulationFrames);
  const applyMergedSimulationFrames = usePlaybackStore((s) => s.applyMergedSimulationFrames);
  const ingestPushFrame = usePlaybackStore((s) => s.ingestPushFrame);
  const clearSimulationTrajectories = usePlaybackStore((s) => s.clearSimulationTrajectories);
  const resetForNewScene = usePlaybackStore((s) => s.resetForNewScene);
  const markSimulationInitialized = usePlaybackStore((s) => s.markSimulationInitialized);
  const setSimulationStatus = usePlaybackStore((s) => s.setSimulationStatus);
  const setStreamStatus = usePlaybackStore((s) => s.setStreamStatus);
  const setError = usePlaybackStore((s) => s.setError);
  const setMqttBrokerStatus = usePlaybackStore((s) => s.setMqttBrokerStatus);
  const setMonitorStatus = usePlaybackStore((s) => s.setMonitorStatus);
  const setPlaying = usePlaybackStore((s) => s.setPlaying);
  const setLatestTimestamp = usePlaybackStore((s) => s.setLatestTimestamp);
  const setScenarioTrajectoryLength = usePlaybackStore((s) => s.setScenarioTrajectoryLength);
  const setActiveScenarioId = usePlaybackStore((s) => s.setActiveScenarioId);
  const setFollowLatestPush = usePlaybackStore((s) => s.setFollowLatestPush);
  const setSpeed = usePlaybackStore((s) => s.setSpeed);
  const seek = usePlaybackStore((s) => s.seek);
  const setActiveSceneGenerationRequestId = usePlaybackStore(
    (s) => s.setActiveSceneGenerationRequestId
  );
  const completeSceneGeneration = usePlaybackStore((s) => s.completeSceneGeneration);
  const setReceivedSimulationModels = usePlaybackStore((s) => s.setReceivedSimulationModels);
  const setControlPanelMode = useUiStore((s) => s.setControlPanelMode);
  const clientRef = useRef<BackendWsClient | null>(null);
  const dispatchMessageRef = useRef<(message: ParsedServerMessage) => void>(() => {});
  const workbenchCluster = useWorkbenchCluster();
  const [driver] = useState(() => new WorkbenchJobDriver());
  useEffect(() => {
    driver.setCluster(workbenchCluster);
  }, [driver, workbenchCluster]);
  useEffect(() => () => driver.stopAll(), [driver]);
  // The trajectories of the loaded scenario, which a simulation on the cluster replays.
  const loadedTrajectoriesRef = useRef<Record<string, unknown> | null>(null);
  const handleTransportError = useCallback(
    (message: string) => {
      if (message === "WebSocket transport issue.") {
        return;
      }
      setError(message);
    },
    [setError]
  );

  const recordPreviewFrames = useCallback((frames: SimulationFrame[]) => {
    const recording = useRecordingStore.getState();
    if (!recording.isRecording) return;
    for (const frame of frames) {
      recording.appendPreviewFrame(frame);
    }
  }, []);

  const ingestPreviewChunk = useCallback(
    async (existing: Parameters<typeof mergeFramesInWorker>[0], incoming: Parameters<typeof mergeFramesInWorker>[1]) => {
      if (shouldMergeFramesInWorker(incoming.length)) {
        try {
          const merged = await mergeFramesInWorker(existing, incoming);
          applyMergedPreviewFrames(merged);
          recordPreviewFrames(incoming);
          return;
        } catch (error) {
          // Never drop a chunk on a worker failure: fall back to the equivalent
          // synchronous store merge instead of losing these frames silently.
          console.error("[SimulationWorkflow] preview merge worker failed; using main-thread merge", error);
        }
      }
      ingestFrames(incoming);
      recordPreviewFrames(incoming);
    },
    [applyMergedPreviewFrames, ingestFrames, recordPreviewFrames]
  );

  const ingestSimulationChunk = useCallback(
    async (existing: Parameters<typeof mergeFramesInWorker>[0], incoming: Parameters<typeof mergeFramesInWorker>[1]) => {
      const recording = useRecordingStore.getState();
      if (shouldMergeFramesInWorker(incoming.length)) {
        try {
          const merged = await mergeFramesInWorker(existing, incoming);
          applyMergedSimulationFrames(merged);
          if (recording.isRecording) {
            for (const frame of incoming) recording.appendSimulationFrame(frame);
          }
          return;
        } catch (error) {
          console.error("[SimulationWorkflow] simulation merge worker failed; using main-thread merge", error);
        }
      }
      ingestSimulationFrames(incoming);
      if (recording.isRecording) {
        for (const frame of incoming) recording.appendSimulationFrame(frame);
      }
    },
    [applyMergedSimulationFrames, ingestSimulationFrames]
  );

  const dispatchMessage = useCallback(
    (message: ParsedServerMessage) => {
      switch (message.kind) {
        case "initial_state": {
          // `scenarioId` is contractually always present and drives routing of the
          // trajectory chunks that follow; fall back to the client-proposed id
          // (captured before the reset) if a message ever omits it.
          const priorScenarioId = usePlaybackStore.getState().activeScenarioId;
          resetForNewScene();
          setControlPanelMode("simulation");
          setActiveScenarioId(message.scenarioId ?? priorScenarioId);
          markSimulationInitialized();
          setPlaying(false);
          setScenarioTrajectoryLength(message.totalTrajectoryLength);
          if (message.totalTrajectoryLength !== null) {
            setLatestTimestamp(message.totalTrajectoryLength);
          }
          break;
        }
        case "preview_trajectory_chunk": {
          const store = usePlaybackStore.getState();
          if (!trajectoryChunkMatchesActiveScenario(store.activeScenarioId, message.scenarioId)) {
            break;
          }
          // The cluster's monitored frames replaced the gateway's plain ones already.
          if (store.previewMonitor.status === "done" && store.previewMonitor.scenarioId === store.activeScenarioId) {
            break;
          }
          const incoming = message.frames;
          enqueuePreviewTrajectoryChunk(async () => {
            const latest = usePlaybackStore.getState();
            if (!trajectoryChunkMatchesActiveScenario(latest.activeScenarioId, message.scenarioId)) {
              return;
            }
            await ingestPreviewChunk(latest.frames, incoming);
          });
          break;
        }
        case "simulation_trajectory_chunk": {
          const store = usePlaybackStore.getState();
          if (!trajectoryChunkMatchesActiveScenario(store.activeScenarioId, message.scenarioId)) {
            break;
          }
          const incoming = message.frames;
          enqueueSimulationTrajectoryChunk(async () => {
            const latest = usePlaybackStore.getState();
            if (!trajectoryChunkMatchesActiveScenario(latest.activeScenarioId, message.scenarioId)) {
              return;
            }
            await ingestSimulationChunk(latest.simulationFrames, incoming);
          });
          break;
        }
        case "generated_scene": {
          const store = usePlaybackStore.getState();
          // Answer to a `monitor_scene` request for a scene loaded from disk.
          if (
            message.requestId !== null &&
            message.requestId === store.pendingSceneMonitorRequestId
          ) {
            store.applySceneMonitorResult(message.requestId, message.scene);
            break;
          }
          const scenePayload = {
            scene: message.scene,
            evaluationData: message.evaluationData ?? undefined,
            valid: message.valid,
          };
          const isBatchRequest =
            !!message.requestId &&
            useBatchGenerationStore.getState().isBatchRequest(message.requestId);
          const livePreview = useUiStore.getState().sceneGenerationLivePreview;
          const shouldVisualize =
            livePreview || (!isBatchRequest && message.valid);
          if (isBatchRequest && message.requestId) {
            if (shouldVisualize) {
              store.setVisualizedScenario(scenePayload);
            }
            useBatchGenerationStore.getState().handleBatchGeneratedScene(message.requestId, scenePayload);
            break;
          }
          const { activeSceneGenerationRequestId } = store;
          if (
            activeSceneGenerationRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== activeSceneGenerationRequestId
          ) {
            break;
          }
          if (message.requestId) {
            if (message.valid) {
              if (shouldVisualize) {
                store.setVisualizedScenario(scenePayload);
              }
              completeSceneGeneration(message.requestId);
            } else if (message.evaluationData) {
              store.recordSceneGenerationEvaluation(message.requestId, message.evaluationData);
            }
          } else {
            if (shouldVisualize) {
              store.setVisualizedScenario(scenePayload);
            }
            if (message.valid) {
              setActiveSceneGenerationRequestId(null);
            }
          }
          break;
        }
        case "trajectory_generation_preview": {
          const tgStore = useTrajectoryGenerationStore.getState();
          if (
            tgStore.activeRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== tgStore.activeRequestId
          ) {
            break;
          }
          const frames = buildFramesFromTrajectoryData(message.trajectoryData);
          if (frames.length > 0) {
            usePlaybackStore.getState().setTrajectoryPreviewFrames(frames);
          }
          const iterNumbers = (message.trajectoryData?.iter_numbers ?? {}) as Record<string, number>;
          const iteration = Object.values(iterNumbers)[0] ?? tgStore.iteration;
          tgStore.markPreview(iteration);
          break;
        }
        case "trajectory_generation_result": {
          const tgStore = useTrajectoryGenerationStore.getState();
          if (
            tgStore.activeRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== tgStore.activeRequestId
          ) {
            break;
          }
          if (message.trajectoryData) {
            const frames = buildFramesFromTrajectoryData(message.trajectoryData);
            if (frames.length > 0) {
              usePlaybackStore.getState().setTrajectoryPreviewFrames(frames);
            }
          }
          tgStore.markResult({
            valid: message.valid,
            complete: message.complete,
            scenarioJson:
              message.valid && message.trajectoryData
                ? JSON.stringify(message.trajectoryData)
                : null,
            errorMessage: message.errorMessage ?? null,
          });
          if (message.errorMessage) {
            setError(message.errorMessage);
          }
          break;
        }
        case "frame": {
          ingestPushFrame(message.frame);
          const recording = useRecordingStore.getState();
          if (recording.isRecording) {
            recording.appendPreviewFrame(message.frame);
          }
          break;
        }
        case "error": {
          setError(message.message);
          // A pending Connect click owns this error: the panel reports it inline with
          // the endpoint-specific hints, which the global banner has no room for.
          const connection = useConnectionStore.getState();
          if (connection.connectionAttempt === "connecting") {
            connection.markConnectionFailed(message.message);
          }
          break;
        }
        case "ack":
          setError(null);
          break;
        case "mqtt_broker_status": {
          setMqttBrokerStatus(message.status, message.masterBroker);
          const connection = useConnectionStore.getState();
          if (message.status === "connected" && connection.connectionAttempt !== "connected") {
            connection.markConnectionSucceeded();
            // Drop the banner left over from a failed attempt: it contradicts the
            // Connected status now showing next to it.
            setError(null);
          }
          break;
        }
        case "monitor_status":
          setMonitorStatus(message.status);
          break;
        case "simulation_status":
          setSimulationStatus(message.status, message.groundControlPortsByAgentId);
          break;
        case "stack_options":
          usePlaybackStore.getState().setStackOptions(message.options);
          break;
        case "simulation_models":
          simulationModelsToken += 1;
          setReceivedSimulationModels({
            vesselModelsByAgentId: message.vesselModelsByAgentId,
            receivedToken: simulationModelsToken,
          });
          break;
        case "unknown":
          console.warn("[SimulationWorkflow] Unknown server message shape", message.raw);
          break;
        default:
          break;
      }
    },
    [
      ingestPreviewChunk,
      ingestSimulationChunk,
      completeSceneGeneration,
      ingestPushFrame,
      markSimulationInitialized,
      resetForNewScene,
      setError,
      setLatestTimestamp,
      setScenarioTrajectoryLength,
      setPlaying,
      setSimulationStatus,
      setMqttBrokerStatus,
      setMonitorStatus,
      setActiveScenarioId,
      setControlPanelMode,
      setActiveSceneGenerationRequestId,
      setReceivedSimulationModels,
    ]
  );

  useEffect(() => {
    dispatchMessageRef.current = dispatchMessage;
    driver.setDispatch(dispatchMessage);
  }, [dispatchMessage, driver]);

  const prepareForSimulationReset = useCallback(() => {
    // Keep loaded scenario/animation chunks, but clear simulation stream data and rewind playback.
    clearSimulationTrajectories();
    setReceivedSimulationModels(null);
    setPlaying(false);
    setFollowLatestPush(false);
    const { frames } = usePlaybackStore.getState();
    if (frames.length > 0) {
      seek(0);
    }
  }, [clearSimulationTrajectories, seek, setFollowLatestPush, setPlaying, setReceivedSimulationModels]);

  const gatewayUrl = gatewayWsUrl(workbenchCluster.operatorUrl);
  useEffect(() => {
    const client = new BackendWsClient(gatewayUrl, {
      onServerMessage: (message) => dispatchMessageRef.current(message),
      onStatus: (status) => {
        setStreamStatus(status);
        if (status === "connected") {
          setError(null);
          // The simulator, ASV software and control layer choices come from the backend's stack resolver.
          client.send({ type: "query_stack_options" });
          return;
        }
        setMqttBrokerStatus("disconnected");
        setMonitorStatus("disconnected");
        if (status === "disconnected" || status === "error") {
          // The gateway's scenario session is gone with the socket. Jobs on the cluster do not
          // depend on it: they keep running and keep reporting.
          usePlaybackStore.getState().setActiveScenarioId(null);
        }
      },
      onError: handleTransportError,
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [gatewayUrl, handleTransportError, setError, setStreamStatus, setMqttBrokerStatus, setMonitorStatus]);

  const loadScenarioFromFile = useCallback(
    async (file: File | null, options: LoadScenarioOptions = {}) => {
      if (!file) {
        return;
      }
      if (usePlaybackStore.getState().streamStatus !== "connected") {
        setError("The workbench server is not connected.");
        return;
      }
      resetForNewScene();
      clearSimulationTrajectories();
      setPlaying(false);
      setFollowLatestPush(false);
      setError(null);
      const scenarioId = crypto.randomUUID();
      setActiveScenarioId(scenarioId);
      const fileContent = await file.text();
      try {
        const raw: unknown = JSON.parse(fileContent);
        loadedTrajectoriesRef.current = isFullTrajectoryScenario(raw) ? (raw as { trajectories: Record<string, unknown> }).trajectories : null;
      } catch {
        loadedTrajectoriesRef.current = null;
      }
      clientRef.current?.send({
        type: "load_scenario_file",
        scenarioId,
        fileName: file.name,
        filePath: file.webkitRelativePath || file.name,
        fileContent,
      });
      void driver.monitorPreview(scenarioId, fileContent, options.colregsConstraintsContent ?? "");
    },
    [
      driver,
      clearSimulationTrajectories,
      resetForNewScene,
      setActiveScenarioId,
      setError,
      setFollowLatestPush,
      setPlaying,
    ]
  );

  return {
    /** @deprecated Use loadScenarioFromFile: loads scenario JSON via load_scenario_file. */
    initializeSimulation: loadScenarioFromFile,
    loadScenarioFromFile,
    startSimulation: () => {
      const currentStatus = usePlaybackStore.getState().simulationStatus;
      if (currentStatus !== "ready to start") {
        return;
      }
      clearSimulationTrajectories();
      setSimulationStatus("agents are preparing", usePlaybackStore.getState().groundControlPortsByAgentId);
      clientRef.current?.send({ type: "start_simulation" });
    },
    resetSimulation: () => {
      prepareForSimulationReset();
      clientRef.current?.send({ type: "reset_simulation" });
    },
    setSpeed: (value: number) => {
      setSpeed(value);
    },
    seek: (value: number) => {
      seek(value);
    },
    sendMessage: (message: ClientToServerMessage) => {
      if (message.type === "initialize_simulation") {
        const missing = missingTrajectoriesReason(
          usePlaybackStore.getState().scenarioTrajectoryLength
        );
        if (missing !== null) {
          setError(missing);
          return;
        }
        prepareForSimulationReset();
        // Enter the local "initializing" state so the UI reflects the in-flight
        // request until the backend reports a concrete simulation_status.
        usePlaybackStore.getState().beginSimulationInitialization();
      }
      clientRef.current?.send(message);
    },
    /** What the active cluster offers for a job type, and why the workbench cannot run it when it cannot. */
    clusterResources: workbenchCluster.resources,
    operatorUrl: workbenchCluster.operatorUrl,
    /** One scene of a batch as a cluster job; resolves when the job ended, its batch row updated. */
    enqueueSceneGeneration: (requestId: string, input: SceneGenerationInput) => driver.generateBatchScene(requestId, input),
    /** One scene as a cluster job, shown on the scene page as it arrives; resolves with its outcome. */
    generateScene: (requestId: string, input: SceneGenerationInput) => driver.generateScene(requestId, input),
    /** Monitors a scene (a scenario file's first scene) on the cluster and merges the verdicts into the shown scene. */
    monitorScene: (requestId: string, scenario: Record<string, unknown>, colregsConstraintsContent: string) =>
      driver.monitorScene(requestId, scenario, colregsConstraintsContent),
    stopSceneGeneration: () => {
      driver.stopScenes();
      usePlaybackStore.getState().cancelSceneGeneration();
      useBatchGenerationStore.getState().markAllBatchStopped();
    },
    generateTrajectories: (
      requestId: string,
      scenarioContent: string,
      colregsConstraintsContent: string,
      params: TrajectoryGenerationParamsWire
    ) => {
      void driver.generateTrajectories(requestId, scenarioContent, colregsConstraintsContent, params);
    },
    stopTrajectoryGeneration: () => {
      driver.stopTrajectories();
    },
    /** Runs the loaded scenario as a simulation job on the cluster; its frames fill the simulation stream. */
    runSimulationOnCluster: (plan: Extract<SimulationRunPlan, { where: "cluster" }>, colregsConstraintsContent: string) => {
      const trajectories = loadedTrajectoriesRef.current;
      if (trajectories === null) {
        setError(NO_TRAJECTORIES_MESSAGE);
        return;
      }
      setFollowLatestPush(false);
      void driver.runSimulation(kinematicSimulationSubmission(plan, trajectories, colregsConstraintsContent), colregsConstraintsContent);
    },
    stopSimulationOnCluster: () => driver.stopSimulation(),
    setClusterRunSpeed: (speed: number) => driver.setSimulationSpeed(speed),
  };
}
