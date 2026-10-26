import { describe, expect, it } from "vitest";
import { describeReason, parseReason, parseReasons, reasonsByStep, reasonsOfEntry, splitByField } from "./reasons";

describe("parseReason", () => {
  it("attaches a scope reason to its entry", () => {
    expect(parseReason("scope.0: no class 'x/y' in the catalog")).toMatchObject({
      step: "scope",
      entry: 0,
      field: null,
      message: "no class 'x/y' in the catalog",
      source: "server",
    });
    expect(parseReason("scope.2: class 'a/b' is in scope.0 already")).toMatchObject({ step: "scope", entry: 2, field: null });
  });

  it("splits the entry from the field of a validation error", () => {
    expect(parseReason("scope.1.quota: Input should be greater than or equal to 1")).toMatchObject({ step: "scope", entry: 1, field: "quota", path: "scope.1.quota" });
    expect(parseReason("scope.0.failure_budget: Input should be greater than or equal to 0")).toMatchObject({ entry: 0, field: "failure_budget" });
  });

  it("attaches a run reason to the run, with or without its name", () => {
    expect(parseReason("execution.runs.1 (usv_navigation): the stack is not available for an unattended run")).toMatchObject({
      step: "runs",
      entry: 1,
      field: null,
      message: "the stack is not available for an unattended run",
    });
    expect(parseReason("execution.runs.0.stack.dt: Input should be greater than 0")).toMatchObject({ step: "runs", entry: 0, field: "stack.dt" });
    expect(parseReason("execution.runs.3: Value error, early_stop needs the live monitor")).toMatchObject({
      entry: 3,
      field: null,
      message: "early_stop needs the live monitor",
    });
  });

  it("maps the sections to their steps and fields", () => {
    expect(parseReason("domain.colregs_constants: Value error, not valid YAML (mapping values are not allowed here)")).toMatchObject({
      step: "domain",
      entry: null,
      field: "colregs_constants",
      message: "not valid YAML (mapping values are not allowed here)",
    });
    expect(parseReason("domain.scene_generation_timeout_s: Input should be greater than 0")).toMatchObject({ step: "domain", field: "scene_generation_timeout_s" });
    expect(parseReason("trajectories: Value error, the straight generator needs timespan_s")).toMatchObject({ step: "trajectories", field: null });
    expect(parseReason("trajectories.params.maxLeafs: Input should be a valid integer")).toMatchObject({ step: "trajectories", field: "params.maxLeafs" });
    expect(parseReason("resources.queue_depth.simulate: Input should be greater than or equal to 1")).toMatchObject({ step: "resources", field: "queue_depth.simulate" });
    expect(parseReason("policy.stop.max_cases: Input should be greater than or equal to 1")).toMatchObject({ step: "policy", field: "stop.max_cases" });
    expect(parseReason("execution.runs: Tuple should have at least 1 item after validation, not 0")).toMatchObject({ step: "runs", entry: null, field: "runs" });
  });

  it("puts the name and description with the scope step", () => {
    expect(parseReason("name: String should have at least 1 character")).toMatchObject({ step: "scope", entry: null, field: "name" });
    expect(parseReason("description: Input should be a valid string")).toMatchObject({ step: "scope", field: "description" });
    expect(parseReason("scope: Tuple should have at least 1 item after validation, not 0")).toMatchObject({ step: "scope", entry: null, field: "scope" });
  });

  it("sends reasons without a path, or about the whole config, to the review step", () => {
    expect(parseReason("not valid YAML: while scanning a simple key")).toMatchObject({ step: "review", entry: null, field: null, path: null });
    expect(parseReason("a campaign config is a mapping of its sections")).toMatchObject({ step: "review" });
    expect(parseReason("config: Value error, something about everything")).toMatchObject({ step: "review", field: "config", message: "something about everything" });
    expect(parseReason("format: Input should be 1")).toMatchObject({ step: "review", field: "format" });
  });

  it("keeps the raw text and the source", () => {
    const reason = parseReason("scope.0: boom", "local");
    expect(reason.raw).toBe("scope.0: boom");
    expect(reason.source).toBe("local");
  });
});

describe("grouping reasons", () => {
  const reasons = parseReasons([
    "scope.0: no class 'a' in the catalog",
    "scope.1.quota: Input should be greater than or equal to 1",
    "execution.runs.0.stack.dt: Input should be greater than 0",
    "execution.runs.0.stack.usv_navigation.goal: Field required",
    "execution.runs.0: unavailable",
    "not valid YAML: x",
  ]);

  it("lists every step, with the reasons of each", () => {
    const grouped = reasonsByStep(reasons);
    expect(grouped.scope).toHaveLength(2);
    expect(grouped.runs).toHaveLength(3);
    expect(grouped.review).toHaveLength(1);
    expect(grouped.domain).toEqual([]);
  });

  it("picks the reasons of one entry", () => {
    expect(reasonsOfEntry(reasonsByStep(reasons).runs, 0)).toHaveLength(3);
    expect(reasonsOfEntry(reasonsByStep(reasons).runs, 1)).toHaveLength(0);
    expect(reasonsOfEntry(reasonsByStep(reasons).scope, 1).map((reason) => reason.field)).toEqual(["quota"]);
  });

  it("separates the reasons a field shows from those the entry shows", () => {
    const { byField, rest } = splitByField(reasonsOfEntry(reasonsByStep(reasons).runs, 0), ["stack.dt", "stack.usv_navigation"]);
    expect([...byField.keys()]).toEqual(["stack.dt", "stack.usv_navigation"]);
    expect(byField.get("stack.usv_navigation")?.[0].field).toBe("stack.usv_navigation.goal");
    expect(rest).toHaveLength(1);
    expect(rest[0].message).toBe("unavailable");
  });

  it("gives a reason to the most specific field that shows it", () => {
    const stackReasons = reasonsOfEntry(reasonsByStep(reasons).runs, 0);
    const { byField, rest } = splitByField(stackReasons, ["stack", "stack.dt", "stack.usv_navigation"]);
    expect(byField.get("stack.dt")).toHaveLength(1);
    expect(byField.get("stack.usv_navigation")).toHaveLength(1);
    expect(byField.has("stack")).toBe(false);
    expect(rest).toHaveLength(1);
    const unknown = splitByField(parseReasons(["execution.runs.0.stack.mode: Input should be 'replay'"]), ["stack", "stack.dt"]);
    expect(unknown.byField.get("stack")).toHaveLength(1);
  });

  it("describes a reason with its field in front", () => {
    expect(describeReason(reasons[1])).toBe("quota: Input should be greater than or equal to 1");
    expect(describeReason(reasons[0])).toBe("no class 'a' in the catalog");
  });
});
