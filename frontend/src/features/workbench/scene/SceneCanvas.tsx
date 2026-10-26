import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  captureSvgScreenshot,
  exportFramesAsCsv,
  exportFramesAsGeoJson,
} from "./sceneExport";
import type { SimulationFrame } from "../../../domain/simulation/types";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
  usePlaybackStore,
} from "../../../domain/playback/playbackStore";
import { useUiStore, type OverlayVisibility } from "../../../app/uiStore";
import { useEncounterSelectionStore } from "../monitor/encounterSelectionStore";
import { buildShipColorsByActorId, getShipColor, getSimulationStreamColor } from "./shipColors";
import { buildTrajectoryPathsByActor } from "./buildTrajectoryPaths";
import { EncounterCanvas, type EncounterCanvasStream } from "./EncounterCanvas";
import { NauticalMapView } from "./NauticalMapView";
import { RecenterControl } from "./RecenterControl";

interface SceneCanvasProps {
  /** When provided, visualizes this generated scene instead of playback preview frames. */
  generatedScene?: SimulationFrame | null;
}

/**
 * The workbench's scene view: the encounter canvas (or the nautical map) fed from the global
 * playback store, with the preview stream and the simulation stream overlaid, the export
 * buttons and the map switch.
 */
export function SceneCanvas({ generatedScene }: SceneCanvasProps = {}) {
  const isGeneratedMode = generatedScene !== undefined;
  const frames = usePlaybackStore((s) => s.frames);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const playbackFrame = usePlaybackStore((s) => getCurrentFrame(s));
  const previewFrame = isGeneratedMode ? generatedScene : playbackFrame;
  const simulationFrame = usePlaybackStore((s) => getCurrentSimulationFrame(s));
  const hasTrajectoryChunk = usePlaybackStore((s) => s.hasTrajectoryChunk);
  const hasSimulationTrajectoryChunk = usePlaybackStore((s) => s.hasSimulationTrajectoryChunk);
  const autoFitPending = usePlaybackStore((s) => s.autoFitPending);
  const consumeAutoFit = usePlaybackStore((s) => s.consumeAutoFit);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const controlPanelMode = useUiStore((s) => s.controlPanelMode);
  const previewOverlays = useUiStore((s) => s.previewOverlays);
  const simulationOverlays = useUiStore((s) => s.simulationOverlays);
  const hidePreviewStream = useUiStore((s) => s.hidePreviewStream);
  const hideSimulationStream = useUiStore((s) => s.hideSimulationStream);
  const sceneViewMode = useUiStore((s) => s.sceneViewMode);
  const setSceneViewMode = useUiStore((s) => s.setSceneViewMode);
  const referenceGeofence = useUiStore((s) => s.referenceGeofence);
  const selectedRelationId = useEncounterSelectionStore((s) => s.selectedRelationId);
  const setSelectedRelationId = useEncounterSelectionStore((s) => s.setSelectedRelationId);

  const [fitSignal, setFitSignal] = useState(0);
  const [nauticalRecenterSignal, setNauticalRecenterSignal] = useState(0);

  const showPreview = isGeneratedMode
    ? generatedScene != null
    : !hidePreviewStream && hasTrajectoryChunk && frames.length > 0;
  const showSimulation =
    !isGeneratedMode &&
    !hideSimulationStream &&
    hasSimulationTrajectoryChunk &&
    simulationFrames.length > 0;

  const generatedFrames = useMemo(() => (generatedScene ? [generatedScene] : []), [generatedScene]);
  const previewFrames = isGeneratedMode ? generatedFrames : frames;
  const actors = useMemo(() => previewFrame?.actors ?? [], [previewFrame]);
  const simActors = useMemo(() => simulationFrame?.actors ?? [], [simulationFrame]);

  const colorByActorId = useMemo(
    () =>
      isGeneratedMode
        ? buildShipColorsByActorId(actors)
        : (Object.fromEntries(actors.map((actor) => [actor.id, getShipColor(actor)])) as Record<string, string>),
    [actors, isGeneratedMode]
  );
  const simulationStreamColorByActorId = useMemo(
    () =>
      Object.fromEntries(simActors.map((actor) => [actor.id, getSimulationStreamColor(actor)])) as Record<
        string,
        string
      >,
    [simActors]
  );

  const streams = useMemo<EncounterCanvasStream[]>(() => {
    const out: EncounterCanvasStream[] = [];
    if (showPreview) {
      out.push({
        key: "preview",
        label: isGeneratedMode ? "Scene" : "Preview",
        frame: previewFrame ?? null,
        frames: previewFrames,
        colorByActorId,
        layers: previewOverlays,
      });
    }
    if (showSimulation) {
      out.push({
        key: "simulation",
        label: "Simulation",
        frame: simulationFrame,
        frames: simulationFrames,
        colorByActorId: simulationStreamColorByActorId,
        layers: simulationOverlays,
        secondary: showPreview,
      });
    }
    return out;
  }, [
    colorByActorId,
    isGeneratedMode,
    previewFrame,
    previewFrames,
    previewOverlays,
    showPreview,
    showSimulation,
    simulationFrame,
    simulationFrames,
    simulationOverlays,
    simulationStreamColorByActorId,
  ]);

  // Fit when a new generated scene is shown or the store asks for it (a new trajectory), and
  // recenter the map when it is opened; derived from the previous values while rendering.
  const wantsAutoFit = !isGeneratedMode && autoFitPending && hasTrajectoryChunk && playbackFrame !== null;
  const [seen, setSeen] = useState({ scene: generatedScene, wantsAutoFit, sceneViewMode });
  if (seen.scene !== generatedScene || seen.wantsAutoFit !== wantsAutoFit || seen.sceneViewMode !== sceneViewMode) {
    const newScene = isGeneratedMode && generatedScene != null && seen.scene !== generatedScene;
    if (newScene || (wantsAutoFit && !seen.wantsAutoFit)) {
      setFitSignal((v) => v + 1);
    }
    if (newScene || (sceneViewMode === "nautical" && seen.sceneViewMode !== "nautical")) {
      setNauticalRecenterSignal((v) => v + 1);
    }
    setSeen({ scene: generatedScene, wantsAutoFit, sceneViewMode });
  }

  const exportActiveFrames = isGeneratedMode
    ? generatedFrames
    : controlPanelMode === "simulation"
      ? simulationFrames
      : frames;
  const exportPrefix = isGeneratedMode
    ? "generated_scene"
    : controlPanelMode === "simulation"
      ? "simulation"
      : "preview";

  const onScreenshot = () => {
    if (svgRef.current) {
      captureSvgScreenshot(svgRef.current, `scene_${exportPrefix}`);
    }
  };

  const viewToggle = (
    <button
      type="button"
      className="scene-view-toggle-btn"
      onClick={() => {
        setSceneViewMode(sceneViewMode === "cartesian" ? "nautical" : "cartesian");
      }}
    >
      {sceneViewMode === "cartesian" ? "Nautical GPS" : "Encounter canvas"}
    </button>
  );
  const exportToolbar = (
    <div className="scene-export-toolbar toolbar-row" aria-label="Export scene">
      {sceneViewMode === "cartesian" ? (
        <button type="button" onClick={onScreenshot}>
          Screenshot
        </button>
      ) : null}
      <button
        type="button"
        disabled={exportActiveFrames.length === 0}
        onClick={() => exportFramesAsCsv(exportActiveFrames, exportPrefix)}
      >
        CSV
      </button>
      <button
        type="button"
        disabled={exportActiveFrames.length === 0}
        onClick={() => exportFramesAsGeoJson(exportActiveFrames, exportPrefix)}
      >
        GeoJSON
      </button>
    </div>
  );

  if (sceneViewMode === "cartesian") {
    return (
      <div className="scene-panel">
        <EncounterCanvas
          streams={streams}
          fitSignal={fitSignal}
          onFit={isGeneratedMode ? undefined : consumeAutoFit}
          selectedRelationId={isGeneratedMode ? null : selectedRelationId}
          onSelectRelation={isGeneratedMode ? undefined : setSelectedRelationId}
          svgRef={(element) => {
            svgRef.current = element;
          }}
          emptyMessage={isGeneratedMode ? "No scene generated or loaded yet." : "Load a scenario to see the encounter."}
        >
          {viewToggle}
          {exportToolbar}
        </EncounterCanvas>
      </div>
    );
  }

  return (
    <NauticalScene
      showPreview={showPreview}
      showSimulation={showSimulation}
      previewFrames={previewFrames}
      previewFrame={previewFrame ?? null}
      simulationFrames={simulationFrames}
      simulationFrame={simulationFrame}
      colorByActorId={colorByActorId}
      simulationColorByActorId={simulationStreamColorByActorId}
      previewOverlays={previewOverlays}
      simulationOverlays={simulationOverlays}
      reference={referenceGeofence}
      recenterSignal={nauticalRecenterSignal}
      onRecenter={() => setNauticalRecenterSignal((v) => v + 1)}
    >
      {viewToggle}
      {exportToolbar}
    </NauticalScene>
  );
}

function NauticalScene({
  showPreview,
  showSimulation,
  previewFrames,
  previewFrame,
  simulationFrames,
  simulationFrame,
  colorByActorId,
  simulationColorByActorId,
  previewOverlays,
  simulationOverlays,
  reference,
  recenterSignal,
  onRecenter,
  children,
}: {
  showPreview: boolean;
  showSimulation: boolean;
  previewFrames: SimulationFrame[];
  previewFrame: SimulationFrame | null;
  simulationFrames: SimulationFrame[];
  simulationFrame: SimulationFrame | null;
  colorByActorId: Record<string, string>;
  simulationColorByActorId: Record<string, string>;
  previewOverlays: OverlayVisibility;
  simulationOverlays: OverlayVisibility;
  reference: { latitude: number; longitude: number };
  recenterSignal: number;
  onRecenter: () => void;
  children: ReactNode;
}) {
  const trajectoriesByActorId = useMemo(
    () => buildTrajectoryPathsByActor(previewFrames, previewFrame),
    [previewFrames, previewFrame]
  );
  const simulationTrajectoriesByActorId = useMemo(
    () => buildTrajectoryPathsByActor(simulationFrames, simulationFrame),
    [simulationFrames, simulationFrame]
  );
  return (
    <div className="scene-panel">
      <div className="canvas-rulers">
        <div className="ruler-top">
          <span>Geofence center lat {reference.latitude.toFixed(6)}</span>
          <span>Nautical map mode</span>
          <span>lon {reference.longitude.toFixed(6)}</span>
        </div>
        <div className="ruler-left">
          <span>Reference (0,0) at geofence center</span>
          <span>Rendered as WGS84</span>
        </div>
        <RecenterControl className="axis-legend" legendMode="nautical" onRecenter={onRecenter} />
      </div>
      <NauticalMapView
        layers={[
          ...(showPreview && previewFrame
            ? [
                {
                  actors: previewFrame.actors,
                  statesByActorId: previewFrame.statesByActorId,
                  trajectoriesByActorId,
                  colorByActorId,
                  showVelocity: previewOverlays.velocity,
                  situationContexts: previewFrame.situationContexts,
                  showManeuveringDomain: previewOverlays.maneuveringDomain,
                },
              ]
            : []),
          ...(showSimulation && simulationFrame
            ? [
                {
                  actors: simulationFrame.actors,
                  statesByActorId: simulationFrame.statesByActorId,
                  trajectoriesByActorId: simulationTrajectoriesByActorId,
                  colorByActorId: simulationColorByActorId,
                  showVelocity: simulationOverlays.velocity,
                  situationContexts: simulationFrame.situationContexts,
                  showManeuveringDomain: simulationOverlays.maneuveringDomain,
                },
              ]
            : []),
        ]}
        reference={reference}
        recenterSignal={recenterSignal}
      />
      {children}
    </div>
  );
}
