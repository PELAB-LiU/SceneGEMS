import { describe, expect, it } from "vitest";
import { laneBands, layoutGraph, type LayoutEdge, type LayoutNode } from "./graphLayout";

const NODES: LayoutNode[] = [
  { id: "a", lane: "one", width: 200, height: 100 },
  { id: "b", lane: "one", width: 200, height: 100 },
  { id: "c", lane: "two", width: 200, height: 100 },
  { id: "d", lane: "three", width: 200, height: 100 },
];
const EDGES: LayoutEdge[] = [
  { id: "ac", source: "a", target: "c" },
  { id: "bc", source: "b", target: "c" },
  { id: "cd", source: "c", target: "d" },
];

describe("layoutGraph", () => {
  it("puts each lane in its own column, left to right in lane order", () => {
    const { positions, bands } = layoutGraph(["one", "two", "three"], NODES, EDGES);
    expect(positions.size).toBe(4);
    const x = (id: string) => positions.get(id)?.x ?? NaN;
    expect(x("a")).toBe(x("b"));
    expect(x("a")).toBeLessThan(x("c"));
    expect(x("c")).toBeLessThan(x("d"));
    expect(bands.map((band) => band.lane)).toEqual(["one", "two", "three"]);
  });

  it("keeps cards of a lane from overlapping", () => {
    const { positions } = layoutGraph(["one", "two", "three"], NODES, EDGES);
    const a = positions.get("a");
    const b = positions.get("b");
    expect(Math.abs((a?.y ?? 0) - (b?.y ?? 0))).toBeGreaterThanOrEqual(100);
  });

  it("makes every band as tall as the graph and wide enough for its cards", () => {
    const { bands } = layoutGraph(["one", "two", "three"], NODES, EDGES);
    expect(new Set(bands.map((band) => band.height)).size).toBe(1);
    expect(bands.every((band) => band.width >= 200)).toBe(true);
    expect(bands[0].x + bands[0].width).toBeLessThan(bands[1].x + 1);
  });

  it("leaves out a lane that has no cards", () => {
    const { bands } = layoutGraph(["one", "empty", "two", "three"], NODES, EDGES);
    expect(bands.map((band) => band.lane)).toEqual(["one", "two", "three"]);
  });

  it("ignores an edge that names a missing node", () => {
    const { positions } = layoutGraph(["one", "two", "three"], NODES, [...EDGES, { id: "bad", source: "a", target: "zzz" }]);
    expect(positions.size).toBe(4);
  });
});


describe("laneBands", () => {
  it("follows a card that was moved: its lane grows to hold it and the bands stay as tall as the graph", () => {
    const { positions, bands } = layoutGraph(["one", "two", "three"], NODES, EDGES);
    const moved = new Map(positions);
    const a = positions.get("a") as { x: number; y: number };
    moved.set("a", { x: a.x - 300, y: a.y + 400 });
    const after = laneBands(["one", "two", "three"], NODES, moved);
    expect(after[0].x).toBeLessThan(bands[0].x);
    expect(after[0].width).toBeGreaterThan(bands[0].width);
    expect(new Set(after.map((band) => band.height)).size).toBe(1);
    expect(after[0].height).toBeGreaterThan(bands[0].height);
    expect([after[1].x, after[1].width]).toEqual([bands[1].x, bands[1].width]);
  });

  it("leaves out a lane without cards", () => {
    const { positions } = layoutGraph(["one", "two", "three"], NODES, EDGES);
    expect(laneBands(["one", "none", "two"], NODES, positions).map((band) => band.lane)).toEqual(["one", "two"]);
  });
});
