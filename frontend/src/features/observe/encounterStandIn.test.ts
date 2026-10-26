import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { frameIndexAt, plotBounds, ruleOutcomes, vesselRows } from "./encounterStandIn";

describe("encounter stand-in helpers", () => {
  it("finds the frame closest to a timestamp", () => {
    expect(frameIndexAt(sampleFrames, undefined)).toBe(0);
    expect(frameIndexAt(sampleFrames, 12.4)).toBe(12);
    expect(frameIndexAt(sampleFrames, 9999)).toBe(sampleFrames.length - 1);
    expect(frameIndexAt([], 3)).toBe(0);
  });

  it("lists the vessels with a state, own ship first", () => {
    const rows = vesselRows(sampleFrames[10]);
    expect(rows.map((row) => row.id)).toEqual(["own_ship", "target_1"]);
    expect(rows[0].ownShip).toBe(true);
    expect(rows[1].state.speed).toBe(5.8);
  });

  it("reads the rule outcomes of a frame, with the situation of each relation", () => {
    const outcomes = ruleOutcomes(sampleFrames[10]);
    expect(outcomes.length).toBeGreaterThan(0);
    expect(outcomes[0].relationId).toBe("own_ship->target_1");
    expect(ruleOutcomes({ ...sampleFrames[10], ruleResults: [] })).toEqual([]);
  });

  it("bounds every position with a margin", () => {
    const bounds = plotBounds(sampleFrames.slice(0, 20));
    expect(bounds).not.toBeNull();
    expect(bounds!.minX).toBeLessThan(50);
    expect(bounds!.maxX).toBeGreaterThan(250 - 0.6 * 19);
    expect(plotBounds([])).toBeNull();
  });
});
