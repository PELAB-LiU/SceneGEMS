import { describe, expect, it } from "vitest";
import { layoutGraph, stackedLayout, type LayoutEdge, type LayoutNode } from "./graphLayout";

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

describe("stackedLayout", () => {
  it("stacks the cards of a lane in the order given and the lanes side by side", () => {
    const { positions } = stackedLayout(["one", "two", "three"], NODES);
    expect(positions.get("a")).toEqual({ x: 0, y: 0 });
    expect(positions.get("b")?.y).toBeGreaterThan(100);
    expect(positions.get("c")?.x).toBeGreaterThan(200);
  });
});
