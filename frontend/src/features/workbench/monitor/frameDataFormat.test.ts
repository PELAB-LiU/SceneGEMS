import { describe, expect, it } from "vitest";
import { asRecord, formatScalar, humanizeKey, sortKeys } from "./frameDataFormat";

describe("frameDataFormat", () => {
  it("asRecord accepts plain objects only", () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord([1])).toBeNull();
    expect(asRecord(null)).toBeNull();
  });

  it("humanizeKey splits camelCase and snake_case", () => {
    expect(humanizeKey("maxSpeed")).toBe("Max Speed");
    expect(humanizeKey("min_length")).toBe("Min length");
  });

  it("formatScalar formats booleans, numbers and empties", () => {
    expect(formatScalar(true)).toBe("Yes");
    expect(formatScalar(null)).toBe("-");
    expect(formatScalar(1.5)).toBe("1.5");
    expect(formatScalar(12345.678)).toBe("1.235e+4");
  });

  it("sortKeys puts priority keys first, rest alphabetical", () => {
    expect(sortKeys(["z", "b", "x", "a"], ["x", "z"])).toEqual(["x", "z", "a", "b"]);
  });
});
