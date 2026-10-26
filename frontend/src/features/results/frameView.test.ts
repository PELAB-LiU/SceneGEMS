import { describe, expect, it } from "vitest";
import { parseFrames } from "../../domain/cluster/framesApi";
import { monitoredFrame, monitoredFrames, RULE_16, RULE_8 } from "../../test/fixtures/monitoredFrames";
import { buildTracks, failedFlags, firstFailureIndex, nearestFrameIndex, relationLabel, relationRows, vesselRows } from "./frameView";

const frames = parseFrames(monitoredFrames(30, 12));

describe("frame view", () => {
  it("finds the frame nearest to a time", () => {
    expect(nearestFrameIndex(frames, 0)).toBe(0);
    expect(nearestFrameIndex(frames, 12.4)).toBe(12);
    expect(nearestFrameIndex(frames, 12.6)).toBe(13);
    expect(nearestFrameIndex(frames, 999)).toBe(29);
    expect(nearestFrameIndex(frames, -5)).toBe(0);
    expect(nearestFrameIndex([], 3)).toBe(0);
  });

  it("flags the frames with a failed rule and finds the first", () => {
    const flags = failedFlags(frames);
    expect(flags.slice(10, 14)).toEqual([false, false, true, true]);
    expect(firstFailureIndex(frames)).toBe(12);
    expect(firstFailureIndex(parseFrames(monitoredFrames(5)))).toBe(-1);
  });

  it("describes each vessel's state with course in compass degrees and speed in knots", () => {
    const rows = vesselRows(frames[10]);
    expect(rows.map((row) => row.name)).toEqual(["OS_0", "TS_1"]);
    const [own, target] = rows;
    expect(own).toMatchObject({ isOwnShip: true, x: 90, y: 120, speedMs: 6.5 });
    expect(own.speedKn).toBeCloseTo(12.64, 1);
    // heading 0 rad is east, so the compass course is 090; pi rad is west, 270
    expect(own.courseDeg).toBeCloseTo(90);
    expect(target.courseDeg).toBeCloseTo(270);
    expect(own.roles).toEqual(["give way to TS_1"]);
    expect(target.roles).toEqual(["stands on for OS_0"]);
  });

  it("names a relation by the vessels' names", () => {
    expect(relationLabel(frames[0], "0->1")).toBe("OS_0 and TS_1");
    expect(relationLabel(frames[0], "7")).toBe("7");
  });

  it("lists the rule outcomes of a frame per encounter, failed first, with the encounter's metrics", () => {
    const [relation] = relationRows(frames[25]);
    expect(relation).toMatchObject({ relationId: "0->1", label: "OS_0 and TS_1", situation: "Crossing from starboard", failed: true });
    expect(relation.rules.map((rule) => [rule.name, rule.result])).toEqual([
      [RULE_16, "FAILED"],
      [RULE_8, "UNKNOWN"],
    ]);
    expect(relation.dcpa).toBe(12.5);
    expect(relation.tcpa).toBe(35);
    expect(relation.distance).toBeCloseTo(225);
    const early = relationRows(frames[2])[0];
    expect(early.failed).toBe(false);
    expect(early.rules.every((rule) => rule.result !== "FAILED")).toBe(true);
  });

  it("builds the tracks of every vessel with the bounds of all positions", () => {
    const { tracks, bounds } = buildTracks(frames);
    expect(tracks.map((track) => [track.name, track.points.length])).toEqual([
      ["OS_0", 30],
      ["TS_1", 30],
    ]);
    expect(bounds).toEqual({ minX: 50, maxX: 450, minY: 120, maxY: 200 });
  });

  it("thins a long run to the most points and keeps the last one", () => {
    const long = parseFrames(Array.from({ length: 1000 }, (_, i) => monitoredFrame({ timestamp: i })));
    const { tracks } = buildTracks(long, 100);
    expect(tracks[0].points.length).toBeLessThanOrEqual(101);
    expect(tracks[0].points[tracks[0].points.length - 1].x).toBe(50 + 999 * 4);
  });

  it("has no bounds without frames", () => {
    expect(buildTracks([])).toEqual({ tracks: [], bounds: null });
  });
});
