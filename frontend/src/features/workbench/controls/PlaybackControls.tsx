import { useCallback, useRef, useState } from "react";
import { useUiStore } from "../../../app/uiStore";
import { Disclosure } from "../../../components/Disclosure";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationStreamControls } from "./types";
import { AnimationPlaybackControls } from "./AnimationPlaybackControls";
import {
  activateLiveMode,
  getLatestSimulationTimestamp,
  handleLivePlayback,
} from "./livePlayback";
import {
  SimulationInitControls,
  type SimulationInitControlsHandle,
} from "./SimulationInitControls";
import { RecordingControls } from "./RecordingControls";
import { groundControlEndpointLabels } from "./simulationInitConfig";

interface Props {
  streamControls: SimulationStreamControls;
}

function getSimulationStatusPresentation(
  status:
    | "running"
    | "starting"
    | "ready to start"
    | "agents are preparing"
    | "initializing"
    | "offline"
    | "not initialized"
): {
  label: string;
  tone:
    | "running"
    | "preparing"
    | "ready"
    | "offline"
    | "initializing"
    | "not-initialized"
    | "unknown";
} {
  switch (status) {
    case "running":
      return { label: "running", tone: "running" };
    case "starting":
      return { label: "starting", tone: "preparing" };
    case "agents are preparing":
      return { label: "agents are preparing", tone: "preparing" };
    case "initializing":
      return { label: "initializing", tone: "initializing" };
    case "ready to start":
      return { label: "agents are ready", tone: "ready" };
    case "offline":
      return { label: "No simulator is connected", tone: "offline" };
    case "not initialized":
      return { label: "not initialized", tone: "not-initialized" };
    default:
      return { label: "unknown", tone: "unknown" };
  }
}

export function PlaybackControls({ streamControls }: Props) {
  const controlPanelMode = useUiStore((s) => s.controlPanelMode);
  const setControlPanelMode = useUiStore((s) => s.setControlPanelMode);

  const isPlaying = usePlaybackStore((s) => s.isPlaying);
  const followLatestPush = usePlaybackStore((s) => s.followLatestPush);
  const followSimulationLive = usePlaybackStore((s) => s.followSimulationLive);
  const simulationStatus = usePlaybackStore((s) => s.simulationStatus);
  const groundControlPorts = usePlaybackStore((s) => s.groundControlPortsByAgentId);
  const groundControlEndpoints = groundControlEndpointLabels(groundControlPorts);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const warapsStatus = usePlaybackStore((s) => s.warapsStatus);
  const latestSimulationTimestamp = getLatestSimulationTimestamp(simulationFrames);
  const simulationStatusUi = getSimulationStatusPresentation(simulationStatus);
  const isSimulationStatusUnknownOrOffline =
    simulationStatus === "offline" ||
    simulationStatus === "not initialized" ||
    simulationStatus === "initializing";
  const canStartSimulation =
    simulationStatus === "ready to start" && !isSimulationStatusUnknownOrOffline;
  const areSimulationControlsDisabled = isSimulationStatusUnknownOrOffline;

  const simInitRef = useRef<SimulationInitControlsHandle>(null);
  const [simInitVesselCount, setSimInitVesselCount] = useState(0);
  const onSimInitVesselCount = useCallback((n: number) => {
    setSimInitVesselCount(n);
  }, []);
  const initializeSimulationDisabled =
    !simulationInitialized || warapsStatus !== "connected";

  return (
    <div className="panel">
      <div className="toolbar-row control-panel-header">
        <h3>Simulation controls</h3>
      </div>
      <div className="scene-gen-tabs" role="tablist" aria-label="Playback source">
        <button
          type="button"
          role="tab"
          aria-selected={controlPanelMode === "animation"}
          className={`scene-gen-tab${controlPanelMode === "animation" ? " active" : ""}`}
          onClick={() => setControlPanelMode("animation")}
        >
          Preview playback
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={controlPanelMode === "simulation"}
          className={`scene-gen-tab${controlPanelMode === "simulation" ? " active" : ""}`}
          onClick={() => setControlPanelMode("simulation")}
        >
          Live simulation
        </button>
      </div>

      {controlPanelMode === "simulation" ? (
        <div className="simulation-panel-status-bar simulation-panel-status-bar--below-tabs">
          <span className="meta simulation-status-heading">Simulation status</span>
          <span className={`simulation-status-label simulation-status-label--inline ${simulationStatusUi.tone}`}>
            {simulationStatusUi.label}
          </span>
          <span className="simulation-status-sep" aria-hidden="true">
            |
          </span>
          <span className="meta simulation-panel-status-meta">
            Buffered frames: {simulationFrames.length}
          </span>
          {groundControlEndpoints.length > 0 ? (
            <>
              <span className="simulation-status-sep" aria-hidden="true">
                |
              </span>
              <span
                className="meta simulation-panel-status-meta"
                title="Connect Mission Planner over TCP to fly these vessels"
              >
                Mission Planner: {groundControlEndpoints.join(", ")}
              </span>
            </>
          ) : null}
        </div>
      ) : null}

      {controlPanelMode === "animation" ? (
        <div className="animation-control-stack">
          <AnimationPlaybackControls
            seek={streamControls.seek}
            setSpeed={streamControls.setSpeed}
          />

          <Disclosure
            id="simulation:record-replay"
            title="Record and replay"
            hint="Save a run or replay a saved one"
            headingLevel={4}
          >
            <RecordingControls />
          </Disclosure>
        </div>
      ) : (
        <div className="simulation-control-stack">
          <div className="toolbar-row simulation-actions-toolbar">
            <button
              className="primary-btn accent"
              type="button"
              disabled={initializeSimulationDisabled}
              onClick={() => simInitRef.current?.initializeSimulation()}
            >
              Initialize Simulation
            </button>
            <button
              className={canStartSimulation ? "primary-btn accent" : undefined}
              type="button"
              onClick={() => {
                streamControls.startSimulation();
                activateLiveMode({ followSimulationLive });
              }}
              disabled={!canStartSimulation}
            >
              Start
            </button>
          </div>
          <Disclosure
            id="simulation:more-actions"
            variant="link"
            headingLevel={null}
            title="More actions"
            openTitle="Fewer actions"
          >
            <div className="toolbar-row">
              <button type="button" onClick={streamControls.resetSimulation}>
                Reset Simulation
              </button>
              <button
                className={`live-btn${followLatestPush && !isPlaying ? " active" : ""}`}
                type="button"
                onClick={() =>
                  handleLivePlayback({
                    liveTimestamp: latestSimulationTimestamp,
                    followSimulationLive,
                  })
                }
                disabled={latestSimulationTimestamp === null || areSimulationControlsDisabled}
              >
                Live
              </button>
              <button
                type="button"
                onClick={() => simInitRef.current?.generateSimulationWorld()}
                disabled={simInitVesselCount === 0}
                title={
                  simInitVesselCount === 0
                    ? "Load a scenario to generate vessel physics models"
                    : undefined
                }
              >
                Generate Vessel Physics Models
              </button>
            </div>
          </Disclosure>
          {simulationInitialized && warapsStatus === "connected" ? (
            <p className="meta simulation-actions-hint">
              Ready: the scenario is loaded and WARA-PS is connected. Initialize, then Start. Vessels
              in the scenario: {simInitVesselCount}.
            </p>
          ) : (
            <ul className="readiness-list" aria-label="Before you can initialize">
              {!simulationInitialized && (
                <li className="is-missing">
                  <span className="readiness-mark" aria-hidden>
                    {"\u2022"}
                  </span>
                  Load a scenario first (Scene Generation or Trajectory Generation).
                </li>
              )}
              {warapsStatus !== "connected" && (
                <li className="is-missing">
                  <span className="readiness-mark" aria-hidden>
                    {"\u2022"}
                  </span>
                  Connect to WARA-PS on the Connections page (now: {warapsStatus}).
                </li>
              )}
            </ul>
          )}

          <SimulationInitControls
            ref={simInitRef}
            streamControls={streamControls}
            onScenarioVesselCount={onSimInitVesselCount}
          />
        </div>
      )}
    </div>
  );
}
