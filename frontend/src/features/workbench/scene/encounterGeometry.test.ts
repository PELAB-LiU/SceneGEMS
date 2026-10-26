import { describe, expect, it } from "vitest";
import {
  bearingSector,
  chooseRingSpacing,
  chooseScaleBar,
  computeCpa,
  courseDeg,
  fitView,
  formatClock,
  formatDegrees,
  formatNm,
  headUpRotation,
  METERS_PER_NM,
  rangeBetween,
  relativeBearingDeg,
  screenDirectionOfBearing,
  screenToWorld,
  trueBearingDeg,
  worldMatrix,
  worldToScreen,
  type ViewTransform,
} from "./encounterGeometry";

const NORTH = Math.PI / 2;
const EAST = 0;
const WEST = Math.PI;

function state(x: number, y: number, speed: number, heading: number) {
  return { x, y, speed, heading };
}

describe("courses and bearings", () => {
  it("turns world headings into courses clockwise from north", () => {
    expect(courseDeg(NORTH)).toBeCloseTo(0);
    expect(courseDeg(EAST)).toBeCloseTo(90);
    expect(courseDeg(WEST)).toBeCloseTo(270);
    expect(courseDeg(-Math.PI / 2)).toBeCloseTo(180);
  });

  it("measures true bearings clockwise from north", () => {
    const origin = { x: 0, y: 0 };
    expect(trueBearingDeg(origin, { x: 0, y: 100 })).toBeCloseTo(0);
    expect(trueBearingDeg(origin, { x: 100, y: 100 })).toBeCloseTo(45);
    expect(trueBearingDeg(origin, { x: 0, y: -5 })).toBeCloseTo(180);
    expect(trueBearingDeg(origin, { x: -3, y: 0 })).toBeCloseTo(270);
  });

  it("measures relative bearings from the bow", () => {
    const own = state(0, 0, 8, NORTH);
    expect(relativeBearingDeg(own, { x: 1000, y: 1000 })).toBeCloseTo(45);
    const eastbound = state(0, 0, 8, EAST);
    // A vessel to the north is on the port beam of an eastbound ship.
    expect(relativeBearingDeg(eastbound, { x: 0, y: 1000 })).toBeCloseTo(270);
  });

  it("names the sectors, with the quarters starting 22.5 degrees abaft the beam", () => {
    expect(bearingSector(0)).toBe("ahead");
    expect(bearingSector(350)).toBe("ahead");
    expect(bearingSector(45)).toBe("starboard bow");
    expect(bearingSector(112)).toBe("starboard beam");
    expect(bearingSector(113)).toBe("starboard quarter");
    expect(bearingSector(180)).toBe("astern");
    expect(bearingSector(247)).toBe("port quarter");
    expect(bearingSector(248)).toBe("port beam");
    expect(bearingSector(300)).toBe("port bow");
  });

  it("measures range", () => {
    expect(rangeBetween({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });
});

describe("closest point of approach", () => {
  it("finds a head-on collision", () => {
    const cpa = computeCpa(state(0, 0, 8, EAST), state(6000, 0, 8, WEST));
    expect(cpa.tcpa).toBeCloseTo(375);
    expect(cpa.dcpa).toBeCloseTo(0);
    expect(cpa.pointA?.x).toBeCloseTo(3000);
    expect(cpa.pointB?.x).toBeCloseTo(3000);
  });

  it("matches the monitor on the recorded crossing (own ship north, target west from 3600, 3600)", () => {
    // The recorded frame at 0 s reports dcpa 0 and tcpa 450 for this geometry.
    const cpa = computeCpa(state(0, 0, 8, NORTH), state(3600, 3600, 8, WEST));
    expect(cpa.tcpa).toBeCloseTo(450);
    expect(cpa.dcpa).toBeCloseTo(0, 6);
  });

  it("passes at a distance when the tracks are offset", () => {
    const cpa = computeCpa(state(0, 0, 5, EAST), state(1000, 200, 5, WEST));
    expect(cpa.tcpa).toBeCloseTo(100);
    expect(cpa.dcpa).toBeCloseTo(200);
  });

  it("reports an opening pair with a negative tcpa and the current range", () => {
    const cpa = computeCpa(state(0, 0, 5, WEST), state(1000, 0, 5, EAST));
    expect(cpa.tcpa).toBeLessThan(0);
    expect(cpa.dcpa).toBeCloseTo(1000);
    expect(cpa.pointA).toBeNull();
  });

  it("has no tcpa when the range does not change", () => {
    const cpa = computeCpa(state(0, 0, 6, NORTH), state(500, 0, 6, NORTH));
    expect(cpa.tcpa).toBeNull();
    expect(cpa.dcpa).toBeCloseTo(500);
  });
});

describe("range rings and scale bar", () => {
  it("keeps at most six rings in the view radius", () => {
    expect(chooseRingSpacing(5 * METERS_PER_NM)).toBeCloseTo(1 * METERS_PER_NM);
    expect(chooseRingSpacing(1 * METERS_PER_NM)).toBeCloseTo(0.25 * METERS_PER_NM);
    expect(chooseRingSpacing(0.2 * METERS_PER_NM)).toBeCloseTo(0.05 * METERS_PER_NM);
    expect(chooseRingSpacing(14 * METERS_PER_NM)).toBeCloseTo(3 * METERS_PER_NM);
    for (const radius of [100, 900, 3000, 12000, 60000]) {
      const spacing = chooseRingSpacing(radius);
      expect(radius / spacing).toBeLessThanOrEqual(6);
    }
  });

  it("caps the spacing for huge views", () => {
    expect(chooseRingSpacing(10_000 * METERS_PER_NM)).toBeCloseTo(50 * METERS_PER_NM);
  });

  it("picks a round scale bar no longer than allowed", () => {
    expect(chooseScaleBar(60)).toEqual({ meters: 50, label: "50 m" });
    expect(chooseScaleBar(1000)).toEqual({ meters: 0.5 * METERS_PER_NM, label: "0.5 nm" });
    expect(chooseScaleBar(2000)).toEqual({ meters: METERS_PER_NM, label: "1 nm" });
  });
});

describe("view transform", () => {
  const base: ViewTransform = { center: { x: 100, y: 200 }, scale: 0.5, rotation: 0, width: 800, height: 600 };

  it("draws north-up with north at the top", () => {
    const p = worldToScreen(base, { x: 100, y: 400 });
    expect(p.x).toBeCloseTo(400);
    expect(p.y).toBeCloseTo(200);
  });

  it("puts the own ship's heading at the top in head-up", () => {
    const view = { ...base, rotation: headUpRotation(EAST) };
    // A point east of the center lies ahead of an eastbound own ship: straight up.
    const ahead = worldToScreen(view, { x: 300, y: 200 });
    expect(ahead.x).toBeCloseTo(400);
    expect(ahead.y).toBeCloseTo(200);
    // North is then on the left.
    const north = screenDirectionOfBearing(view, 0);
    expect(north.x).toBeCloseTo(-1);
    expect(north.y).toBeCloseTo(0);
  });

  it("round-trips between world and screen under rotation", () => {
    const view = { ...base, rotation: 0.7 };
    const world = { x: -250, y: 931 };
    const back = screenToWorld(view, worldToScreen(view, world));
    expect(back.x).toBeCloseTo(world.x);
    expect(back.y).toBeCloseTo(world.y);
  });

  it("builds an SVG matrix that agrees with worldToScreen", () => {
    const view = { ...base, rotation: 1.1 };
    const [a, b, c, d, e, f] = worldMatrix(view)
      .replace(/matrix\(|\)/g, "")
      .split(" ")
      .map(Number) as [number, number, number, number, number, number];
    const world = { x: 37, y: -12 };
    const s = worldToScreen(view, world);
    expect(a * world.x + c * world.y + e).toBeCloseTo(s.x);
    expect(b * world.x + d * world.y + f).toBeCloseTo(s.y);
  });

  it("fits the vessels' extent into the free area", () => {
    const insets = { top: 0, right: 0, bottom: 0, left: 0 };
    const fit = fitView(
      [
        { x: 0, y: 0, radius: 0 },
        { x: 1000, y: 0, radius: 0 },
      ],
      0,
      1000,
      1000,
      insets
    )!;
    expect(fit.scale).toBeCloseTo(1);
    expect(fit.center.x).toBeCloseTo(500);
    expect(fit.center.y).toBeCloseTo(0);
  });

  it("centers the extent in the area left free by the insets, also head-up", () => {
    const points = [
      { x: 0, y: 0, radius: 10 },
      { x: 300, y: 800, radius: 10 },
      { x: -200, y: 500, radius: 10 },
    ];
    const insets = { top: 40, right: 60, bottom: 20, left: 10 };
    for (const rotation of [0, headUpRotation(EAST), 0.4]) {
      const fit = fitView(points, rotation, 800, 600, insets)!;
      const view = { center: fit.center, scale: fit.scale, rotation, width: 800, height: 600 };
      for (const p of points) {
        const s = worldToScreen(view, p);
        expect(s.x).toBeGreaterThanOrEqual(insets.left - 1e-6);
        expect(s.x).toBeLessThanOrEqual(800 - insets.right + 1e-6);
        expect(s.y).toBeGreaterThanOrEqual(insets.top - 1e-6);
        expect(s.y).toBeLessThanOrEqual(600 - insets.bottom + 1e-6);
      }
    }
  });

  it("keeps a minimum extent around a single vessel", () => {
    const fit = fitView([{ x: 5, y: 5, radius: 0 }], 0, 300, 300, { top: 0, right: 0, bottom: 0, left: 0 })!;
    expect(fit.scale).toBeCloseTo(1);
    expect(fitView([], 0, 300, 300, { top: 0, right: 0, bottom: 0, left: 0 })).toBeNull();
  });
});

describe("formatting", () => {
  it("formats distances, courses and clock times", () => {
    expect(formatNm(120)).toBe("120 m");
    expect(formatNm(METERS_PER_NM * 1.234)).toBe("1.23 nm");
    expect(formatDegrees(5.4)).toBe("005°");
    expect(formatDegrees(359.7)).toBe("000°");
    expect(formatClock(275)).toBe("4:35");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatClock(-30)).toBe("-0:30");
  });
});
