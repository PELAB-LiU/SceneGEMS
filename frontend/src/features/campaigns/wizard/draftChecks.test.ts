import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import type { BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { emptyDraft, emptyRun, type WizardDraft } from "./wizardState";

const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsed.stacks, generators: parsed.trajectory_generators };

function validDraft(): WizardDraft {
  const draft = emptyDraft();
  draft.name = "sweep";
  draft.scope = [{ id: "s", classes: [], patterns: ["2vessel_*"], quota: 3, failureBudget: 1 }];
  draft.runs = [emptyRun("kinematic.replay")];
  return draft;
}

function messages(draft: WizardDraft, withCatalog: BuilderCatalog | null = catalog) {
  return checkDraft(draft, withCatalog).map((reason) => `${reason.step}/${reason.entry ?? "-"}/${reason.field ?? "-"}`);
}

describe("checkDraft", () => {
  it("accepts a complete draft", () => {
    expect(checkDraft(validDraft(), catalog)).toEqual([]);
  });

  it("asks for a name and a scope", () => {
    const draft = emptyDraft();
    draft.runs = [emptyRun("kinematic.replay")];
    expect(messages(draft)).toEqual(["scope/-/name", "scope/0/-"]);
  });

  it("checks the quota and the failure budget of each entry", () => {
    const draft = validDraft();
    draft.scope[0].quota = 0;
    draft.scope.push({ id: "t", classes: ["a/b"], patterns: [], quota: null, failureBudget: -1 });
    expect(messages(draft)).toEqual(["scope/0/quota", "scope/1/quota", "scope/1/failure_budget"]);
  });

  it("parses customized domain text and flags what is not a YAML mapping", () => {
    const draft = validDraft();
    draft.domain.custom = true;
    draft.domain.colregsConstants = "A: 1\nB: 2\n";
    draft.domain.vesselTypes = "A: [1\n";
    draft.domain.obstacleTypes = "- just\n- a list\n";
    expect(messages(draft)).toEqual(["domain/-/vessel_types", "domain/-/obstacle_types"]);
    draft.domain.colregsConstants = "A: 1\nA: 2\n";
    expect(messages(draft)).toContain("domain/-/colregs_constants");
  });

  it("does not look at domain texts while the defaults are used", () => {
    const draft = validDraft();
    draft.domain.colregsConstants = "not: [valid";
    expect(checkDraft(draft, catalog)).toEqual([]);
  });

  it("requires the generator's required parameters", () => {
    const draft = validDraft();
    draft.trajectories.generator = "straight";
    expect(messages(draft)).toEqual(["trajectories/-/timespan_s"]);
    draft.trajectories.parameters = { timespan_s: 60 };
    expect(checkDraft(draft, catalog)).toEqual([]);
    draft.trajectories.generator = "unheard_of";
    expect(messages(draft)).toEqual(["trajectories/-/generator"]);
  });

  it("flags a run without a stack, with an unknown stack, or with an unavailable one", () => {
    const draft = validDraft();
    draft.runs = [emptyRun(""), emptyRun("kinematic.nope")];
    expect(messages(draft)).toEqual(["runs/0/stack", "runs/1/stack"]);
    const unavailable: BuilderCatalog = { ...catalog, stacks: catalog.stacks.map((stack) => ({ ...stack, available: false, reasons: ["resolver says no"] })) };
    draft.runs = [emptyRun("kinematic.replay")];
    const reasons = checkDraft(draft, unavailable);
    expect(reasons).toHaveLength(1);
    expect(reasons[0].message).toContain("resolver says no");
  });

  it("flags early stop without the live monitor and repeats below 1", () => {
    const draft = validDraft();
    Object.assign(draft.runs[0], { earlyStop: true, repeats: 0 });
    expect(messages(draft)).toEqual(["runs/0/early_stop", "runs/0/repeats"]);
    Object.assign(draft.runs[0], { monitor: "live", repeats: 1 });
    expect(checkDraft(draft, catalog)).toEqual([]);
  });

  it("requires the USV Navigation values once the group is set", () => {
    const draft = validDraft();
    draft.runs = [{ ...emptyRun("kinematic.usv_navigation"), groups: { usv_navigation: { speed: 4 } } }];
    expect(messages(draft)).toEqual([
      "runs/0/stack.usv_navigation.goal",
      "runs/0/stack.usv_navigation.safety_radius",
      "runs/0/stack.usv_navigation.control_horizon",
    ]);
  });

  it("does not judge stacks before the catalog is loaded", () => {
    const draft = validDraft();
    draft.runs = [emptyRun("")];
    expect(checkDraft(draft, null)).toEqual([]);
  });

  it("flags a label value without a name", () => {
    const draft = validDraft();
    draft.resources.labels = [{ key: "", value: "lab" }];
    expect(messages(draft)).toEqual(["resources/-/required_labels"]);
  });
});
