import type { ActorKinematicState } from "../../../domain/simulation/types";

/**
 * Nautical geometry of the encounter canvas and the pair cards.
 *
 * World frame as the backend sends it: x east, y north (meters), heading in radians
 * counterclockwise from east, speed in m/s along the heading. Nautical values are derived
 * from it: course and bearings in degrees clockwise from true north, speed in knots,
 * distances in nautical miles.
 */

export const METERS_PER_NM = 1852;
export const KNOTS_PER_MS = 3600 / METERS_PER_NM;

export interface Point {
  x: number;
  y: number;
}

function wrap360(degrees: number): number {
  const wrapped = degrees % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}

/** Course over ground in degrees true (0 = north, 90 = east) of a world heading. */
export function courseDeg(headingRad: number): number {
  return wrap360(90 - (headingRad * 180) / Math.PI);
}

export function velocityOf(state: ActorKinematicState): Point {
  return { x: Math.cos(state.heading) * state.speed, y: Math.sin(state.heading) * state.speed };
}

export function rangeBetween(from: Point, to: Point): number {
  return Math.hypot(to.x - from.x, to.y - from.y);
}

/** True bearing in degrees of `to` seen from `from`. */
export function trueBearingDeg(from: Point, to: Point): number {
  return wrap360((Math.atan2(to.x - from.x, to.y - from.y) * 180) / Math.PI);
}

/** Bearing of `to` relative to the bow of `from` (0 ahead, 90 starboard beam, 270 port beam). */
export function relativeBearingDeg(from: ActorKinematicState, to: Point): number {
  return wrap360(trueBearingDeg(from, to) - courseDeg(from.heading));
}

export type BearingSector =
  | "ahead"
  | "starboard bow"
  | "starboard beam"
  | "starboard quarter"
  | "astern"
  | "port quarter"
  | "port beam"
  | "port bow";

const SECTORS: BearingSector[] = [
  "ahead",
  "starboard bow",
  "starboard beam",
  "starboard quarter",
  "astern",
  "port quarter",
  "port beam",
  "port bow",
];

/**
 * Eight 45 degree sectors centered on ahead, beam and astern. The quarters start 22.5
 * degrees abaft the beam (112.5 and 247.5), the limit of the sternlight sector that
 * decides overtaking in Rule 13.
 */
export function bearingSector(relativeDeg: number): BearingSector {
  return SECTORS[Math.floor(wrap360(relativeDeg + 22.5) / 45) % 8]!;
}

export interface CpaResult {
  /** Seconds to the closest point of approach; negative once it lies behind, null when the range does not change. */
  tcpa: number | null;
  /** Distance at the closest point ahead: the current range when the vessels are opening. */
  dcpa: number;
  /** Each vessel's position at the CPA, only when it lies ahead (tcpa > 0). */
  pointA: Point | null;
  pointB: Point | null;
}

const MIN_RELATIVE_SPEED_SQ = 1e-9;

/**
 * Closest point of approach of two vessels holding course and speed (straight-line
 * extrapolation of the current states). This is the same definition as the monitor's
 * `tcpa` and `dcpa` metrics; the frontend computes it to place the CPA on the canvas
 * and for frames without monitor metrics.
 */
export function computeCpa(a: ActorKinematicState, b: ActorKinematicState): CpaResult {
  const va = velocityOf(a);
  const vb = velocityOf(b);
  const px = b.x - a.x;
  const py = b.y - a.y;
  const vx = vb.x - va.x;
  const vy = vb.y - va.y;
  const vv = vx * vx + vy * vy;
  const range = Math.hypot(px, py);
  if (vv < MIN_RELATIVE_SPEED_SQ) {
    return { tcpa: null, dcpa: range, pointA: null, pointB: null };
  }
  const tcpa = -(px * vx + py * vy) / vv;
  if (tcpa <= 0) {
    return { tcpa, dcpa: range, pointA: null, pointB: null };
  }
  return {
    tcpa,
    dcpa: Math.hypot(px + vx * tcpa, py + vy * tcpa),
    pointA: { x: a.x + va.x * tcpa, y: a.y + va.y * tcpa },
    pointB: { x: b.x + vb.x * tcpa, y: b.y + vb.y * tcpa },
  };
}

/** Ring spacings in nautical miles, the steps a radar offers. */
const RING_SPACINGS_NM = [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 4, 5, 10, 20, 25, 50];

/**
 * Range ring spacing (meters) for a view whose shorter half-extent is `radiusMeters`: the
 * smallest radar step that keeps at most `maxRings` rings inside that radius.
 */
export function chooseRingSpacing(radiusMeters: number, maxRings = 6): number {
  const radiusNm = Math.max(radiusMeters, 1) / METERS_PER_NM;
  const step =
    RING_SPACINGS_NM.find((spacing) => radiusNm / spacing <= maxRings) ??
    RING_SPACINGS_NM[RING_SPACINGS_NM.length - 1]!;
  return step * METERS_PER_NM;
}

const SCALE_BAR_STEPS_M = [10, 20, 50, 100];
const SCALE_BAR_STEPS_NM = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50];

/** Longest round scale bar not longer than `maxMeters`: meters below 0.1 nm, nautical miles above. */
export function chooseScaleBar(maxMeters: number): { meters: number; label: string } {
  let best = { meters: SCALE_BAR_STEPS_M[0]!, label: `${SCALE_BAR_STEPS_M[0]} m` };
  for (const meters of SCALE_BAR_STEPS_M) {
    if (meters <= maxMeters) {
      best = { meters, label: `${meters} m` };
    }
  }
  for (const nm of SCALE_BAR_STEPS_NM) {
    const meters = nm * METERS_PER_NM;
    if (meters <= maxMeters) {
      best = { meters, label: `${nm} nm` };
    }
  }
  return best;
}

export type Orientation = "north-up" | "head-up";

/** Screen rotation that puts a heading at the top of the screen (head-up); 0 is north-up. */
export function headUpRotation(headingRad: number): number {
  return Math.PI / 2 - headingRad;
}

export interface ViewTransform {
  /** World point at the middle of the view. */
  center: Point;
  /** Pixels per meter. */
  scale: number;
  /** Counterclockwise rotation of the world on screen, radians. */
  rotation: number;
  width: number;
  height: number;
}

export function worldToScreen(view: ViewTransform, p: Point): Point {
  const dx = p.x - view.center.x;
  const dy = p.y - view.center.y;
  const cos = Math.cos(view.rotation);
  const sin = Math.sin(view.rotation);
  return {
    x: view.width / 2 + (dx * cos - dy * sin) * view.scale,
    y: view.height / 2 - (dx * sin + dy * cos) * view.scale,
  };
}

export function screenToWorld(view: ViewTransform, s: Point): Point {
  const rx = (s.x - view.width / 2) / view.scale;
  const ry = -(s.y - view.height / 2) / view.scale;
  const cos = Math.cos(view.rotation);
  const sin = Math.sin(view.rotation);
  return {
    x: view.center.x + rx * cos + ry * sin,
    y: view.center.y - rx * sin + ry * cos,
  };
}

/** SVG `matrix(a b c d e f)` that maps world coordinates to screen pixels. */
export function worldMatrix(view: ViewTransform): string {
  const cos = Math.cos(view.rotation);
  const sin = Math.sin(view.rotation);
  const a = view.scale * cos;
  const b = -view.scale * sin;
  const c = -view.scale * sin;
  const d = -view.scale * cos;
  const e = view.width / 2 - (a * view.center.x + c * view.center.y);
  const f = view.height / 2 - (b * view.center.x + d * view.center.y);
  return `matrix(${a} ${b} ${c} ${d} ${e} ${f})`;
}

/** Screen direction (unit vector, y down) of a true bearing under the view's rotation. */
export function screenDirectionOfBearing(view: ViewTransform, bearingDeg: number): Point {
  const rad = (bearingDeg * Math.PI) / 180;
  const wx = Math.sin(rad);
  const wy = Math.cos(rad);
  const cos = Math.cos(view.rotation);
  const sin = Math.sin(view.rotation);
  return { x: wx * cos - wy * sin, y: -(wx * sin + wy * cos) };
}

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * View center and scale (pixels per meter) that fit every point, with its radius, into the
 * view minus `insets` (room for the controls laid over it), under the view's rotation. The
 * points' extent is centered in the free area; it is at least `minHalfExtent` meters each way.
 */
export function fitView(
  points: { x: number; y: number; radius: number }[],
  rotation: number,
  width: number,
  height: number,
  insets: Insets,
  minHalfExtent = 150
): { center: Point; scale: number } | null {
  if (points.length === 0) {
    return null;
  }
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (const p of points) {
    const u = p.x * cos - p.y * sin;
    const v = p.x * sin + p.y * cos;
    minU = Math.min(minU, u - p.radius);
    maxU = Math.max(maxU, u + p.radius);
    minV = Math.min(minV, v - p.radius);
    maxV = Math.max(maxV, v + p.radius);
  }
  const midU = (minU + maxU) / 2;
  const midV = (minV + maxV) / 2;
  const spanU = Math.max(maxU - minU, 2 * minHalfExtent);
  const spanV = Math.max(maxV - minV, 2 * minHalfExtent);
  const freeW = Math.max(width - insets.left - insets.right, 40);
  const freeH = Math.max(height - insets.top - insets.bottom, 40);
  const scale = Math.min(freeW / spanU, freeH / spanV);
  // Put the extent's middle at the middle of the free area, not of the whole view.
  const freeX = insets.left + freeW / 2;
  const freeY = insets.top + freeH / 2;
  const cu = midU - (freeX - width / 2) / scale;
  const cv = midV + (freeY - height / 2) / scale;
  return { center: { x: cu * cos + cv * sin, y: -cu * sin + cv * cos }, scale };
}

export function formatNm(meters: number): string {
  const nm = meters / METERS_PER_NM;
  if (nm < 0.1) {
    return `${Math.round(meters)} m`;
  }
  return `${nm < 10 ? nm.toFixed(2) : nm.toFixed(1)} nm`;
}

export function formatKnots(speedMs: number): string {
  return `${(speedMs * KNOTS_PER_MS).toFixed(1)} kn`;
}

export function formatDegrees(degrees: number): string {
  return `${String(Math.round(wrap360(degrees)) % 360).padStart(3, "0")}°`;
}

/** Scenario time or a duration as m:ss, or h:mm:ss from one hour. */
export function formatClock(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${sign}${h}:${String(m).padStart(2, "0")}:${ss}` : `${sign}${m}:${ss}`;
}
