import { describe, expect, it } from "vitest";
import { threeVesselFrames, twoVesselFrames } from "../../encounter/fixtures/recordedFrames";
import type { SimulationFrame } from "../../../domain/simulation/types";
import {
  buildRuleTimeline,
  firstFailureAtOrBefore,
  niceTimeStep,
  pairSummarySegments,
  ruleTag,
  valueAt,
} from "./ruleTimelineModel";

const R16 = "Rule 16: Give-Way Vessel Takes Early and Substantial Action";

describe("buildRuleTimeline on the recorded two-vessel crossing", () => {
  const timeline = buildRuleTimeline(twoVesselFrames());
  const pair = timeline.pairs[0]!;

  it("spans the run plus one time step", () => {
    expect(timeline.start).toBe(0);
    expect(timeline.end).toBe(730);
    expect(timeline.pairs.map((p) => p.relationId)).toEqual(["0->1"]);
  });

  it("joins the encounter type into segments", () => {
    expect(pair.encounter.map((s) => [s.start, s.end, s.value.type])).toEqual([
      [0, 390, "CROSSING_FROM_PORT"],
      [390, 730, "OTHER"],
    ]);
  });

  it("keeps one track per rule and subject, rules before suggestions, encounter-wide rules first", () => {
    expect(pair.rules.map((r) => `${ruleTag(r)} ${r.subjectActorName}`)).toEqual([
      "R8 ",
      "R8 OS_0",
      "R16 OS_0",
      "Tip OS_0",
    ]);
  });

  it("records the results over time and the first failure", () => {
    const r16 = pair.rules.find((r) => r.ruleName === R16)!;
    expect(r16.segments.map((s) => [s.start, s.end, s.value])).toEqual([
      [10, 70, "UNKNOWN"],
      [70, 730, "FAILED"],
    ]);
    expect(r16.firstFailure).toBe(70);
    expect(valueAt(r16.segments, 5)).toBeNull();
    expect(valueAt(r16.segments, 69)).toBe("UNKNOWN");
    expect(valueAt(r16.segments, 70)).toBe("FAILED");
    expect(firstFailureAtOrBefore(r16, 60)).toBeNull();
    expect(firstFailureAtOrBefore(r16, 400)).toBe(70);
  });

  it("summarises a pair by its worst rule result", () => {
    expect(pairSummarySegments(pair).map((s) => [s.start, s.end, s.value])).toEqual([
      [10, 70, "UNKNOWN"],
      [70, 730, "FAILED"],
    ]);
  });
});

describe("buildRuleTimeline on the recorded three-vessel run", () => {
  const timeline = buildRuleTimeline(threeVesselFrames());

  it("orders own ship pairs first", () => {
    expect(timeline.pairs.map((p) => p.relationId)).toEqual(["0->1", "0->2", "1->2"]);
  });

  it("tracks a rule for each vessel of the head-on", () => {
    const headOn = timeline.pairs.find((p) => p.relationId === "0->2")!;
    expect(headOn.encounter[0]!.value.type).toBe("HEAD_ON");
    const r16 = headOn.rules.filter((r) => r.ruleName === R16);
    expect(r16.map((r) => [r.subjectActorName, r.firstFailure])).toEqual([
      ["OS_0", 70],
      ["TS_2", 70],
    ]);
  });

  it("keeps a pair in no encounter with its single rule", () => {
    const other = timeline.pairs.find((p) => p.relationId === "1->2")!;
    expect(other.encounter.map((s) => s.value.type)).toEqual(["OTHER"]);
    expect(other.rules.every((r) => r.firstFailure === null)).toBe(true);
  });
});

describe("buildRuleTimeline edge cases", () => {
  it("is empty without frames", () => {
    expect(buildRuleTimeline([])).toEqual({ start: 0, end: 0, pairs: [] });
  });

  it("uses the given time step for the last frame and leaves gaps for missing rules", () => {
    const frames = twoVesselFrames();
    const first = frames[2]!;
    const gap: SimulationFrame = { ...frames[3]!, ruleResults: [] };
    const last = frames[4]!;
    const timeline = buildRuleTimeline([first, gap, last], 2);
    expect(timeline.end).toBe(last.timestamp + 2);
    const track = timeline.pairs[0]!.rules[0]!;
    expect(track.segments.map((s) => [s.start, s.end])).toEqual([
      [first.timestamp, gap.timestamp],
      [last.timestamp, last.timestamp + 2],
    ]);
  });
});

describe("niceTimeStep", () => {
  it("keeps at most eight ticks on round steps", () => {
    expect(niceTimeStep(720)).toBe(120);
    expect(niceTimeStep(60)).toBe(10);
    expect(niceTimeStep(3600)).toBe(600);
    expect(niceTimeStep(10 ** 7)).toBe(14400);
  });
});
