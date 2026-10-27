import { PopoverMenu } from "../../../components/PopoverMenu";
import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import type { OverlayVisibility } from "../../../app/uiStore";
import { usePersistedState } from "../../../app/usePersistedState";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { encounterTagsByVessel, frameRelations } from "../monitor/encounterPairs";
import {
  chooseRingSpacing,
  courseDeg,
  fitView,
  formatDegrees,
  formatNm,
  headUpRotation,
  rangeBetween,
  screenToWorld,
  trueBearingDeg,
  worldToScreen,
  type Orientation,
  type Point,
  type ViewTransform,
} from "./encounterGeometry";
import { CANVAS_COLORS, CANVAS_FONT } from "./encounterPalette";
import { actorTracksFor, cpaMarks, splitTrack, type ActorTrack } from "./encounterScene";
import {
  BearingScale,
  CanvasLegend,
  CpaLayer,
  DomainLayer,
  HullLayer,
  NorthArrow,
  RangeRings,
  SafetyRadiusLayer,
  ScaleBar,
  SelectionLine,
  TrackLayer,
  VesselLabels,
  VesselOverlay,
  WorldGroup,
  type TrackDrawing,
  type VesselScreenInfo,
} from "./nauticalLayers";
import "./encounterCanvas.css";

/** One set of frames drawn on the canvas (the workbench overlays a preview and a simulation). */
export interface EncounterCanvasStream {
  key: string;
  /** Legend text when more than one stream is drawn. */
  label: string;
  /** Frame at the play head. */
  frame: SimulationFrame | null;
  /** Every buffered frame, sorted by timestamp, for the tracks. */
  frames: SimulationFrame[];
  colorByActorId: Record<string, string>;
  layers: OverlayVisibility;
  /** Drawn as a twin of the primary stream: outlined hulls, thicker track, no labels or CPA marks. */
  secondary?: boolean;
}

export interface EncounterCanvasProps {
  streams: EncounterCanvasStream[];
  /** Changing this number fits the view to the vessels (once a frame and a size exist). */
  fitSignal?: number;
  /** Called after each fit. */
  onFit?: () => void;
  selectedRelationId?: string | null;
  onSelectRelation?: (relationId: string | null) => void;
  /** Controls laid over the canvas's top right (export, map switch). */
  children?: ReactNode;
  /** Receives the SVG element (for screenshots). */
  svgRef?: (element: SVGSVGElement | null) => void;
  emptyMessage?: string;
}

interface CanvasSettings {
  orientation: Orientation;
  vectorMinutes: number;
  rings: boolean;
  cpa: boolean;
  labels: boolean;
  legend: boolean;
}

const DEFAULT_SETTINGS: CanvasSettings = {
  orientation: "north-up",
  vectorMinutes: 6,
  rings: true,
  cpa: true,
  labels: true,
  legend: true,
};

const VECTOR_MINUTES = [1, 3, 6, 12, 30];
const MIN_SCALE = 1e-5;
const MAX_SCALE = 40;
const HISTORY_DOT_SECONDS = 60;
/** Room kept free of vessels when fitting: the toolbar above, the north arrow and actions right, the scale bar below. */
const FIT_INSETS = { top: 60, right: 70, bottom: 40, left: 24 };

interface ViewState {
  /**
   * View center relative to the anchor (the own ship, or the vessels' centroid), in the
   * view's rotated frame (u right, v up on screen), so head-up keeps the own ship in place
   * as its heading changes.
   */
  offset: Point;
  /** Pixels per meter. */
  scale: number;
}

/** A world displacement in the view's rotated frame, and back. */
function toViewFrame(d: Point, rotation: number): Point {
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return { x: d.x * cos - d.y * sin, y: d.x * sin + d.y * cos };
}

function fromViewFrame(d: Point, rotation: number): Point {
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return { x: d.x * cos + d.y * sin, y: -d.x * sin + d.y * cos };
}

function centroid(frame: SimulationFrame | null): Point | null {
  const states = frame ? Object.values(frame.statesByActorId) : [];
  if (states.length === 0) {
    return null;
  }
  return {
    x: states.reduce((sum, s) => sum + s.x, 0) / states.length,
    y: states.reduce((sum, s) => sum + s.y, 0) / states.length,
  };
}

function historyDots(track: ActorTrack | undefined, t: number, view: ViewTransform, speed: number): Point[] {
  if (!track || speed * HISTORY_DOT_SECONDS * view.scale < 6) {
    return [];
  }
  const out: Point[] = [];
  for (let i = 0; i < track.t.length && track.t[i]! <= t; i += 1) {
    if (track.t[i]! % HISTORY_DOT_SECONDS === 0 && track.t[i]! > 0) {
      out.push(worldToScreen(view, track.points[i]!));
    }
  }
  return out;
}

/**
 * The 2D encounter canvas in a nautical presentation: north-up or head-up around the own
 * ship, range rings, a true bearing scale, hulls to scale with heading lines, course and
 * speed vectors with time marks, the past track and the path ahead, the CPA of each
 * encounter, safety and maneuvering domains, and each vessel's encounters and roles.
 * Drag pans, the wheel zooms around the pointer, double-click or Fit recenters on the own
 * ship. It draws what its streams give it and reads no store.
 */
export function EncounterCanvas({
  streams,
  fitSignal = 0,
  onFit,
  selectedRelationId = null,
  onSelectRelation,
  children,
  svgRef,
  emptyMessage = "No scene to show yet.",
}: EncounterCanvasProps) {
  const [settings, setSettings] = usePersistedState<CanvasSettings>("encounter-canvas", DEFAULT_SETTINGS);
  const merged = { ...DEFAULT_SETTINGS, ...settings };
  const update = (patch: Partial<CanvasSettings>) => setSettings((prev) => ({ ...DEFAULT_SETTINGS, ...prev, ...patch }));

  const hostRef = useRef<HTMLDivElement | null>(null);
  const svgElementRef = useRef<SVGSVGElement | null>(null);
  const readoutRef = useRef<HTMLSpanElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [view, setView] = useState<ViewState>({ offset: { x: 0, y: 0 }, scale: 0.1 });
  const [pendingFit, setPendingFit] = useState(true);
  /** The user zoomed or panned since the last fit: a resize then keeps the view. */
  const [adjusted, setAdjusted] = useState(false);
  const [fittedSize, setFittedSize] = useState(size);
  const [seenFitSignal, setSeenFitSignal] = useState(fitSignal);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((prev) =>
        Math.abs(prev.width - width) < 0.5 && Math.abs(prev.height - height) < 0.5 ? prev : { width, height }
      );
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  if (fitSignal !== seenFitSignal) {
    setSeenFitSignal(fitSignal);
    setPendingFit(true);
  }

  const visibleStreams = streams.filter((stream) => stream.frame);
  const primary = visibleStreams.find((stream) => !stream.secondary) ?? visibleStreams[0] ?? null;
  const frame = primary?.frame ?? null;
  const ownActor = frame?.actors.find((actor) => actor.isOwnShip) ?? null;
  const ownState = ownActor && frame ? frame.statesByActorId[ownActor.id] : undefined;
  const anchor: Point = ownState ? { x: ownState.x, y: ownState.y } : (centroid(frame) ?? { x: 0, y: 0 });
  const headUp = merged.orientation === "head-up" && Boolean(ownState);
  const rotation = headUp && ownState ? headUpRotation(ownState.heading) : 0;

  const transform: ViewTransform = {
    center: (() => {
      const d = fromViewFrame(view.offset, rotation);
      return { x: anchor.x + d.x, y: anchor.y + d.y };
    })(),
    scale: view.scale,
    rotation,
    width: Math.max(size.width, 1),
    height: Math.max(size.height, 1),
  };
  const transformRef = useRef(transform);
  useEffect(() => {
    transformRef.current = transform;
  });

  /** The view centered on the anchor that fits every vessel, or null before a frame and a size exist. */
  const computeFitView = (): ViewState | null => {
    const points = visibleStreams.flatMap((stream) =>
      stream.frame!.actors
        .map((actor) => {
          const state = stream.frame!.statesByActorId[actor.id];
          return state ? { x: state.x, y: state.y, radius: Math.max(actor.safetyRadius, actor.length / 2, 20) } : null;
        })
        .filter((p): p is { x: number; y: number; radius: number } => p !== null)
    );
    if (size.width < 20 || size.height < 20) {
      return null;
    }
    const fitted = fitView(points, rotation, size.width, size.height, FIT_INSETS);
    if (!fitted) {
      return null;
    }
    return {
      offset: toViewFrame({ x: fitted.center.x - anchor.x, y: fitted.center.y - anchor.y }, rotation),
      scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, fitted.scale)),
    };
  };
  const [fitCount, setFitCount] = useState(0);
  const resized = fittedSize.width !== size.width || fittedSize.height !== size.height;
  if (pendingFit || (resized && !adjusted)) {
    const next = computeFitView();
    if (next) {
      setPendingFit(false);
      setView(next);
      setFittedSize(size);
      setAdjusted(false);
      setFitCount((count) => count + 1);
    }
  }
  const fit = () => {
    const next = computeFitView();
    if (next) {
      setView(next);
      setFittedSize(size);
      setAdjusted(false);
      setFitCount((count) => count + 1);
    }
  };
  const reportedFit = useRef(0);
  useEffect(() => {
    if (fitCount !== reportedFit.current) {
      reportedFit.current = fitCount;
      onFit?.();
    }
  }, [fitCount, onFit]);

  // Wheel zoom around the pointer; a native listener so the page does not scroll.
  useEffect(() => {
    const svg = svgElementRef.current;
    if (!svg) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const current = transformRef.current;
      const factor = Math.exp(-event.deltaY * 0.0015);
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
      const before = screenToWorld(current, pointer);
      const after = screenToWorld({ ...current, scale }, pointer);
      setAdjusted(true);
      setView((prev) => ({
        scale,
        offset: (() => {
          const d = toViewFrame({ x: before.x - after.x, y: before.y - after.y }, current.rotation);
          return { x: prev.offset.x + d.x, y: prev.offset.y + d.y };
        })(),
      }));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const dragRef = useRef<{ id: number; last: Point; moved: boolean } | null>(null);
  const pointerPosition = (event: ReactPointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    dragRef.current = { id: event.pointerId, last: pointerPosition(event), moved: false };
  };
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const p = pointerPosition(event);
    const drag = dragRef.current;
    if (drag && drag.id === event.pointerId) {
      if (!drag.moved && Math.hypot(p.x - drag.last.x, p.y - drag.last.y) < 3) {
        return;
      }
      if (!drag.moved) {
        drag.moved = true;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      const current = transformRef.current;
      const from = screenToWorld(current, drag.last);
      const to = screenToWorld(current, p);
      drag.last = p;
      setAdjusted(true);
      const d = toViewFrame({ x: from.x - to.x, y: from.y - to.y }, current.rotation);
      setView((prev) => ({ ...prev, offset: { x: prev.offset.x + d.x, y: prev.offset.y + d.y } }));
      return;
    }
    const readout = readoutRef.current;
    if (readout) {
      const world = screenToWorld(transformRef.current, p);
      const reference = ownState ? `${formatNm(rangeBetween(ownState, world))} ${formatDegrees(trueBearingDeg(ownState, world))} from ${ownActor?.name ?? "own ship"} · ` : "";
      readout.textContent = `${reference}x ${Math.round(world.x)} m, y ${Math.round(world.y)} m`;
    }
  };
  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.id === event.pointerId) {
      dragRef.current = null;
    }
  };
  const onPointerLeave = () => {
    if (readoutRef.current) {
      readoutRef.current.textContent = "";
    }
  };


  const marks = merged.cpa ? cpaMarks(frame, { selectedRelationId }) : [];
  const tags = encounterTagsByVessel(frame);

  const vesselClick = (() => {
    if (!onSelectRelation || !frame || !ownActor) {
      return undefined;
    }
    const relations = frameRelations(frame);
    return (actorId: string) => {
      if (actorId === ownActor.id) {
        onSelectRelation(null);
        return;
      }
      const relation = relations.find(
        (r) =>
          (r.actor1Id === ownActor.id && r.actor2Id === actorId) || (r.actor2Id === ownActor.id && r.actor1Id === actorId)
      );
      onSelectRelation(relation && relation.relationId !== selectedRelationId ? relation.relationId : null);
    };
  })();

  const ready = size.width > 0 && size.height > 0;
  const minSide = Math.min(transform.width, transform.height);
  const ringCenter = worldToScreen(transform, anchor);
  const ringSpacing = chooseRingSpacing(minSide / 2 / transform.scale);
  const vectorSeconds = merged.vectorMinutes * 60;

  const streamLayers = visibleStreams.map((stream) => {
    const streamFrame = stream.frame!;
    const tracks = actorTracksFor(stream.frames);
    const vessels: VesselScreenInfo[] = streamFrame.actors
      .map((actor) => {
        const state = streamFrame.statesByActorId[actor.id];
        return state ? { actor, state, screen: worldToScreen(transform, state) } : null;
      })
      .filter((v): v is VesselScreenInfo => v !== null);
    const trackDrawings: TrackDrawing[] = stream.layers.trajectory
      ? streamFrame.actors.map((actor) => {
          const state = streamFrame.statesByActorId[actor.id];
          const { past, ahead } = splitTrack(
            tracks[actor.id],
            streamFrame.timestamp,
            state ? { x: state.x, y: state.y } : null,
            streamFrame.trajectoriesByActorId?.[actor.id]
          );
          return { actorId: actor.id, past, ahead };
        })
      : [];
    const dots: Record<string, Point[]> = {};
    if (stream.layers.trajectory && !stream.secondary) {
      for (const vessel of vessels) {
        dots[vessel.actor.id] = historyDots(tracks[vessel.actor.id], streamFrame.timestamp, transform, vessel.state.speed);
      }
    }
    return { stream, streamFrame, vessels, trackDrawings, dots };
  });

  const primaryLayer = streamLayers.find((layer) => layer.stream === primary) ?? null;
  const selectedPair = (() => {
    if (!selectedRelationId || !frame) return null;
    const [aId, bId] = selectedRelationId.split("->");
    const a = aId ? frame.statesByActorId[aId] : undefined;
    const b = bId ? frame.statesByActorId[bId] : undefined;
    if (!a || !b) return null;
    return {
      a: worldToScreen(transform, a),
      b: worldToScreen(transform, b),
      label: `${formatNm(rangeBetween(a, b))} · ${formatDegrees(trueBearingDeg(a, b))}`,
    };
  })();

  const bearingTargets =
    ownActor && ownState && frame
      ? frame.actors
          .filter((actor) => actor.id !== ownActor.id && frame.statesByActorId[actor.id])
          .map((actor) => ({
            key: actor.id,
            bearing: trueBearingDeg(ownState, frame.statesByActorId[actor.id]!),
            color: primary?.colorByActorId[actor.id] ?? "#94a3b8",
          }))
      : [];

  return (
    <div className="enc-canvas" ref={hostRef}>
      <svg
        ref={(element) => {
          svgElementRef.current = element;
          svgRef?.(element);
        }}
        className="enc-canvas-svg"
        width={transform.width}
        height={transform.height}
        viewBox={`0 0 ${transform.width} ${transform.height}`}
        xmlns="http://www.w3.org/2000/svg"
        fontFamily={CANVAS_FONT}
        role="img"
        aria-label="Encounter canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onDoubleClick={() => fit()}
      >
        <rect width={transform.width} height={transform.height} fill={CANVAS_COLORS.sea} />
        {ready && frame ? (
          <>
            {merged.rings ? <RangeRings center={ringCenter} spacing={ringSpacing} view={transform} /> : null}
            {merged.rings && ownState ? (
              <BearingScale
                center={ringCenter}
                radius={minSide * 0.46}
                view={transform}
                ownCourse={courseDeg(ownState.heading)}
                ownColor={primary?.colorByActorId[ownActor!.id] ?? "#06b6d4"}
                targets={bearingTargets}
              />
            ) : null}
            <WorldGroup view={transform}>
              {streamLayers.map(({ stream, streamFrame }) => (
                <DomainLayer
                  key={`domains-${stream.key}`}
                  frame={streamFrame}
                  colorByActorId={stream.colorByActorId}
                  showSafety={stream.layers.safetyDomain}
                  showStatic={stream.layers.staticAvoidanceDomain}
                  showManeuvering={stream.layers.maneuveringDomain}
                  dim={Boolean(stream.secondary)}
                />
              ))}
              {streamLayers.map(({ stream, streamFrame }) =>
                stream.layers.safetyRadius ? (
                  <SafetyRadiusLayer key={`radius-${stream.key}`} frame={streamFrame} colorByActorId={stream.colorByActorId} />
                ) : null
              )}
              {streamLayers.map(({ stream, trackDrawings }) => (
                <TrackLayer
                  key={`tracks-${stream.key}`}
                  tracks={trackDrawings}
                  colorByActorId={stream.colorByActorId}
                  secondary={Boolean(stream.secondary)}
                />
              ))}
              {streamLayers.map(({ stream, streamFrame }) =>
                stream.layers.dot ? (
                  <HullLayer
                    key={`hulls-${stream.key}`}
                    frame={streamFrame}
                    colorByActorId={stream.colorByActorId}
                    secondary={Boolean(stream.secondary)}
                  />
                ) : null
              )}
            </WorldGroup>
            {primary && marks.length > 0 ? (
              <CpaLayer
                marks={marks}
                view={transform}
                colorByActorId={primary.colorByActorId}
                selectedRelationId={selectedRelationId}
              />
            ) : null}
            {streamLayers.map(({ stream, vessels, dots }) => (
              <VesselOverlay
                key={`overlay-${stream.key}`}
                vessels={vessels}
                view={transform}
                colorByActorId={stream.colorByActorId}
                showSymbols={stream.layers.dot}
                showVectors={stream.layers.velocity}
                vectorSeconds={vectorSeconds}
                historyDots={dots}
                secondary={Boolean(stream.secondary)}
                onVesselClick={stream === primary ? vesselClick : undefined}
              />
            ))}
            {selectedPair ? <SelectionLine a={selectedPair.a} b={selectedPair.b} label={selectedPair.label} /> : null}
            {merged.labels && primaryLayer ? (
              <VesselLabels
                vessels={primaryLayer.vessels}
                colorByActorId={primaryLayer.stream.colorByActorId}
                tagsByVessel={tags}
                bounds={{ x: 4, y: 36, width: transform.width - 8, height: transform.height - 40 }}
              />
            ) : null}
            <ScaleBar view={transform} />
            <NorthArrow view={transform} headUp={headUp} />
            {merged.legend && transform.height >= 300 && transform.width >= 420 ? (
              <CanvasLegend
                view={transform}
                vectorMinutes={merged.vectorMinutes}
                streams={visibleStreams.map((stream) => ({
                  key: stream.key,
                  label: stream.label,
                  color: ownActor ? (stream.colorByActorId[ownActor.id] ?? "#94a3b8") : "#94a3b8",
                  secondary: Boolean(stream.secondary),
                }))}
              />
            ) : null}
          </>
        ) : null}
      </svg>

      {!frame ? <p className="enc-canvas-empty">{emptyMessage}</p> : null}

      <div className="enc-canvas-toolbar" role="toolbar" aria-label="Canvas view">
        <button type="button" className="enc-toggle" onClick={() => fit()} title="Fit every vessel into the view (double-click)">
          Fit view
        </button>
        <PopoverMenu label="View options" ariaLabel="View options">
          <div className="enc-seg" role="group" aria-label="Orientation">
            <button
              type="button"
              className={merged.orientation === "north-up" ? "is-active" : ""}
              aria-pressed={merged.orientation === "north-up"}
              onClick={() => {
                update({ orientation: "north-up" });
                setPendingFit(true);
              }}
            >
              North up
            </button>
            <button
              type="button"
              className={merged.orientation === "head-up" ? "is-active" : ""}
              aria-pressed={merged.orientation === "head-up"}
              disabled={!ownState}
              title={ownState ? "Own ship's heading at the top" : "Head-up needs an own ship"}
              onClick={() => {
                update({ orientation: "head-up" });
                setPendingFit(true);
              }}
            >
              Head up
            </button>
          </div>
          <label className="enc-select">
            <span>Vector length</span>
            <select value={merged.vectorMinutes} onChange={(event) => update({ vectorMinutes: Number(event.target.value) })}>
              {VECTOR_MINUTES.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} min
                </option>
              ))}
            </select>
          </label>
          <div className="enc-toggle-group" role="group" aria-label="Show on the canvas">
            {(
              [
                ["rings", "Range rings"],
                ["cpa", "CPA"],
                ["labels", "Labels"],
                ["legend", "Legend"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`enc-toggle${merged[key] ? " is-active" : ""}`}
                aria-pressed={merged[key]}
                onClick={() => update({ [key]: !merged[key] })}
              >
                {label}
              </button>
            ))}
          </div>
        </PopoverMenu>
        {children ? <div className="enc-canvas-actions">{children}</div> : null}
      </div>
      <span className="enc-canvas-readout" ref={readoutRef} aria-live="off" />
    </div>
  );
}
