import { describe, expect, it } from "vitest";
import { buildActorNameMap, formatRelationId } from "./actorNames";

describe("actorNames", () => {
  it("maps actor ids to names and falls back to the id", () => {
    const names = buildActorNameMap([
      { id: "0", name: "OS_0" },
      { id: "1", name: "" },
    ] as never);
    expect(names).toEqual({ "0": "OS_0", "1": "1" });
    expect(buildActorNameMap(undefined)).toEqual({});
  });

  it("formats relation ids with names", () => {
    expect(formatRelationId("0->1", { "0": "OS_0", "1": "TS_1" })).toBe("OS_0 - TS_1");
    expect(formatRelationId("0->2", { "0": "OS_0" })).toBe("OS_0 - 2");
  });
});
