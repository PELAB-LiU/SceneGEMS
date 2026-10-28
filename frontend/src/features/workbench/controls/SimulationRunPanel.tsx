import { useCallback, useRef, useState } from "react";
import "./simulationPanel.css";
import { useUiStore } from "../../../app/uiStore";
import { Disclosure } from "../../../components/Disclosure";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import { isClusterRunActive, useClusterRunStore, type ClusterRunStatus } from "../cluster/clusterRunStore";
import { describeClusterPlan, isPacedByWatchSpeed, KINEMATIC_SIMULATION_JOB, planSimulationRun, type SimulationSetup } from "../cluster/simulationJobs";
import { describeResources } from "../cluster/workbenchResources";
import { activateLiveMode, getLatestSimulationTimestamp } from "./livePlayback";
import { RecordingControls } from "./RecordingControls";
import { groundControlEndpointLabels } from "./simulationInitConfig";
import { SimulationInitControls, type SimulationInitControlsHandle } from "./SimulationInitControls";
import type { SimulationStreamControls } from "./types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { PageInputPanel } from "../pages/PageInputPanel";
import { forgetSimulationRun, inputOfFile, trajectoriesOfTrajectoryPage, trajectoryContentOfDocument } from "../pages/pageHandoff";
import { useSimulationPageStore, type PageInput } from "../pages/pageStore";
import { RunRecordingStatus } from "../pages/RunRecordingStatus";

interface Props {
  streamControls: SimulationStreamControls;
  colregsConstraintsContent: string;
}

type Tone = "running" | "preparing" | "ready" | "offline" | "initializing" | "not-initialized";

const RUN_SPEEDS = [1, 5, 10, 50, 200] as const;

const CLUSTER_STATUS: Record<ClusterRunStatus, { label: string; tone: Tone }> = {
  idle: { label: "ready to run", tone: "ready" },
  queued: { label: "queued", tone: "preparing" },
  running: { label: "running", tone: "running" },
  finishing: { label: "finishing", tone: "preparing" },
  done: { label: "finished", tone: "ready" },
  failed: { label: "failed", tone: "offline" },
  stopped: { label: "stopped", tone: "not-initialized" },
};

const SESSION_STATUS: Record<string, { label: string; tone: Tone }> = {
  running: { label: "running", tone: "running" },
  starting: { label: "starting", tone: "preparing" },
  "agents are preparing": { label: "agents are preparing", tone: "preparing" },
  initializing: { label: "initializing", tone: "initializing" },
  "ready to start": { label: "agents are ready", tone: "ready" },
  offline: { label: "no simulator connected", tone: "offline" },
  "not initialized": { label: "not initialized", tone: "not-initialized" },
};

/**
 * The simulation's one control panel. The setup decides where the run happens: on the cluster
 * as one job (Run), or as a live session on the master over the MQTT broker (Initialize, then
 * Start). Playback itself lives in the bar under the canvas.
 */
export function SimulationRunPanel({ streamControls, colregsConstraintsContent }: Props) {
  const setWorkbenchView = useUiStore((s) => s.setWorkbenchView);
  const simulationStatus = usePlaybackStore((s) => s.simulationStatus);
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const brokerStatus = usePlaybackStore((s) => s.mqttBrokerStatus);
  const followSimulationLive = usePlaybackStore((s) => s.followSimulationLive);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const groundControlPorts = usePlaybackStore((s) => s.groundControlPortsByAgentId);
  const previewMonitor = usePlaybackStore((s) => s.previewMonitor);
  const run = useClusterRunStore();
  const input = useSimulationPageStore((s) => s.input);
  const trajectoryPageHasResult = useTrajectoryGenerationStore((s) => s.resultValid && s.resultScenarioJson !== null);
  const streamStatus = usePlaybackStore((s) => s.streamStatus);

  const simInitRef = useRef<SimulationInitControlsHandle>(null);
  const [setup, setSetup] = useState<SimulationSetup | null>(null);
  const onSetupChange = useCallback((next: SimulationSetup) => setSetup(next), []);

  const plan = setup ? planSimulationRun(setup) : null;
  const onCluster = plan?.where === "cluster";
  const resources = streamControls.clusterResources(plan?.where === "cluster" ? plan.jobType : KINEMATIC_SIMULATION_JOB);
  const clusterActive = isClusterRunActive(run.status);
  const sessionStatus = SESSION_STATUS[simulationStatus] ?? { label: simulationStatus, tone: "not-initialized" as Tone };
  const status = onCluster ? CLUSTER_STATUS[run.status] : sessionStatus;
  const endpoints = groundControlEndpointLabels(groundControlPorts);
  const latestTimestamp = getLatestSimulationTimestamp(simulationFrames);

  const blockers: string[] = [];
  // A cluster run needs only the input (a loaded run replays and runs again without the gateway session).
  if (!simulationInitialized && !(onCluster && input !== null && simulationFrames.length > 0)) {
    blockers.push("Choose the input trajectories above: from the Trajectory Generation page, Campaign History or a file.");
  }
  if (onCluster && resources.blocker) {
    blockers.push(resources.blocker);
  }
  if (!onCluster && brokerStatus !== "connected") {
    blockers.push("A live session needs the MQTT broker: connect it on the Connections page.");
  }

  const canRunOnCluster = onCluster && blockers.length === 0 && !clusterActive;
  const canInitialize = !onCluster && blockers.length === 0;
  const canStart = !onCluster && simulationStatus === "ready to start";
  const sessionStarted = simulationStatus === "running" || simulationStatus === "starting";

  // The input's trajectories go to the gateway session and the cluster run; a new input replaces the shown run.
  const takeInput = async (picked: PageInput, content: string | null) => {
    if (content === null) {
      throw new Error("The file holds no trajectories (a trajectories.scene_list).");
    }
    forgetSimulationRun();
    await streamControls.setSimulationInput(picked, content, { colregsConstraintsContent });
  };

  const runOnCluster = () => {
    if (plan?.where !== "cluster") {
      return;
    }
    streamControls.runSimulationOnCluster(plan, colregsConstraintsContent);
    activateLiveMode({ followSimulationLive });
  };

  return (
    <div className="panel sim-run-panel">
      <div className="sim-run-header">
        <h3>Simulation</h3>
        <span className={`simulation-status-label simulation-status-label--inline ${status.tone}`} role="status">
          {status.label}
        </span>
        <div className="sim-run-actions">
          {onCluster ? (
            clusterActive ? (
              <button type="button" onClick={streamControls.stopSimulationOnCluster}>
                Stop
              </button>
            ) : (
              <button type="button" className="primary-btn accent" disabled={!canRunOnCluster} onClick={runOnCluster}>
                Run on the cluster
              </button>
            )
          ) : (
            <>
              <button
                type="button"
                className={canStart || sessionStarted ? undefined : "primary-btn accent"}
                disabled={!canInitialize}
                onClick={() => simInitRef.current?.initializeSimulation()}
              >
                Initialize
              </button>
              <button
                type="button"
                className={canStart ? "primary-btn accent" : undefined}
                disabled={!canStart}
                onClick={() => {
                  streamControls.startSimulation();
                  activateLiveMode({ followSimulationLive });
                }}
              >
                Start
              </button>
              <button type="button" disabled={simulationStatus === "not initialized"} onClick={streamControls.resetSimulation}>
                Reset
              </button>
            </>
          )}
        </div>
      </div>

      <PageInputPanel
        title="Input trajectories"
        input={input}
        emptyText="none yet."
        previousLabel="Use the trajectories of the Trajectory Generation page"
        previousAvailable={trajectoryPageHasResult && streamStatus === "connected"}
        onUsePrevious={async () => {
          const handoff = trajectoriesOfTrajectoryPage();
          if (handoff !== null) {
            await takeInput(handoff.input, handoff.content);
          }
        }}
        historyStep="trajectory_generation"
        client={streamControls.operatorClient}
        onPickHistory={(picked, document) => takeInput(picked, trajectoryContentOfDocument(document))}
        onPickFile={async (file) => takeInput(inputOfFile(file.name), trajectoryContentOfDocument(JSON.parse(await file.text())))}
        disabled={clusterActive || sessionStarted || streamStatus !== "connected"}
      />
      <PageEntryStatus store={useSimulationPageStore} />
      {!onCluster ? <RunRecordingStatus /> : null}
      <p className="meta sim-run-where">
        {plan === null
          ? "Set up the vessels below."
          : plan.where === "cluster"
            ? `${describeClusterPlan(plan)} Cluster: ${describeResources(resources)}.`
            : `Runs as a live session on the master over the MQTT broker. ${plan.reason}`}
      </p>
      {onCluster && run.message && run.status !== "idle" ? <p className="meta sim-run-message">{run.message}</p> : null}
      {previewMonitor.status === "running" || previewMonitor.status === "failed" ? (
        <p className="meta sim-run-message">
          {previewMonitor.status === "running" ? previewMonitor.message : `The preview stays unmonitored: ${previewMonitor.message}`}
        </p>
      ) : null}
      {endpoints.length > 0 ? (
        <p className="meta sim-run-message" title="Connect Mission Planner over TCP to fly these vessels">
          Mission Planner: {endpoints.join(", ")}
        </p>
      ) : null}

      {blockers.length > 0 ? (
        <ul className="readiness-list" aria-label="Before the simulation can run">
          {blockers.map((blocker) => (
            <li key={blocker} className="is-missing">
              <span className="readiness-mark" aria-hidden>
                {"•"}
              </span>
              {blocker}
              {blocker.includes("Connections page") ? (
                <button type="button" className="link-btn" onClick={() => setWorkbenchView("connections")}>
                  Open Connections
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {plan?.where === "cluster" && clusterActive && isPacedByWatchSpeed(plan) ? (
        <label className="field sim-run-speed">
          <span>Watch at</span>
          <select value={run.speed} onChange={(e) => streamControls.setClusterRunSpeed(Number(e.target.value))}>
            {RUN_SPEEDS.map((speed) => (
              <option key={speed} value={speed}>
                {speed}x real time
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <SimulationInitControls ref={simInitRef} streamControls={streamControls} onSetupChange={onSetupChange} />

      <Disclosure id="simulation:more-actions" title="More" hint="Follow live, vessel models, record and replay" headingLevel={4} className="sim-init-subpanel">
        <div className="toolbar-row">
          <button type="button" disabled={latestTimestamp === null} onClick={() => activateLiveMode({ followSimulationLive })}>
            Follow the newest frame
          </button>
          {!onCluster && setup?.simulatorType === "Gazebo" ? (
            <button type="button" disabled={(setup?.vessels.length ?? 0) === 0} onClick={() => simInitRef.current?.generateSimulationWorld()}>
              Generate Gazebo vessel models
            </button>
          ) : null}
        </div>
        <RecordingControls />
      </Disclosure>
    </div>
  );
}
