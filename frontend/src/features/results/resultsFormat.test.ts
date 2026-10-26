import { describe, expect, it } from "vitest";
import { compassCourse, describeStack, formatBytes, formatSeconds, metersPerSecondToKnots, runLabel, shortClassId, shortHash, sortedArtifacts } from "./resultsFormat";

describe("results formatting", () => {
  it("formats seconds", () => {
    expect(formatSeconds(null)).toBe("-");
    expect(formatSeconds(12.5)).toBe("12.5 s");
    expect(formatSeconds(31.2000001)).toBe("31.2 s");
    expect(formatSeconds(65)).toBe("1 min 05 s");
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KiB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MiB");
    expect(formatBytes(null)).toBe("");
  });

  it("shortens hashes and class ids", () => {
    expect(shortHash("abcdef0123456789", 6)).toBe("abcdef");
    expect(shortHash(null)).toBe("-");
    expect(shortClassId("short")).toBe("short");
    expect(shortClassId("a".repeat(60), 20)).toBe(`...${"a".repeat(17)}`);
  });

  it("labels runs and stacks", () => {
    expect(runLabel(1, 2)).toBe("run 1, repeat 2");
    expect(runLabel(0)).toBe("run 0");
    expect(runLabel(null)).toBe("-");
    expect(describeStack({ simulation_layer: "kinematic", mode: "usv_navigation", dt: 0.1 })).toBe("kinematic usv_navigation");
    expect(describeStack({ other: 1 })).toBe('{"other":1}');
  });

  it("converts a heading (radians counterclockwise from east) to a compass course", () => {
    expect(compassCourse(0)).toBeCloseTo(90);
    expect(compassCourse(Math.PI / 2)).toBeCloseTo(0);
    expect(compassCourse(-Math.PI / 2)).toBeCloseTo(180);
    expect(compassCourse(Math.PI)).toBeCloseTo(270);
    expect(metersPerSecondToKnots(1)).toBeCloseTo(1.9438, 3);
  });

  it("lists the state log and frames of a run first", () => {
    expect(sortedArtifacts({ zeta: "z", frames: "f", state_log: "s", alpha: "a" }).map(([role]) => role)).toEqual(["state_log", "frames", "alpha", "zeta"]);
  });
});
