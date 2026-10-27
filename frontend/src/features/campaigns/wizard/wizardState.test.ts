import { describe, expect, it } from "vitest";
import { MemoryStorage } from "../../../test/memoryStorage";
import { createWizardStore, emptyDraft, normalizeDraft, WIZARD_STORAGE_KEY } from "./wizardState";

function storeWith(storage = new MemoryStorage()) {
  return { store: createWizardStore(storage), storage };
}

describe("wizard store", () => {
  it("starts with an empty draft at the scope step", () => {
    const { store } = storeWith();
    expect(store.getState().step).toBe("scope");
    expect(store.getState().draft).toMatchObject({ name: "", scope: [{ quota: 1, failureBudget: 0 }], runs: [{ monitor: "post_hoc" }] });
  });

  it("changes a copy of the draft and notifies", () => {
    const { store } = storeWith();
    const before = store.getState().draft;
    store.getState().update((draft) => {
      draft.name = "sweep";
      draft.runs[0].stackId = "kinematic.replay";
    });
    expect(store.getState().draft.name).toBe("sweep");
    expect(store.getState().draft.runs[0].stackId).toBe("kinematic.replay");
    expect(before.name).toBe("");
  });

  it("remembers the steps left behind", () => {
    const { store } = storeWith();
    store.getState().setStep("domain");
    store.getState().setStep("runs");
    store.getState().setStep("domain");
    expect(store.getState().visited).toEqual(["scope", "domain", "runs"]);
  });

  it("keeps the draft per browser: a new store on the same storage finds it", () => {
    const first = storeWith();
    first.store.getState().update((draft) => {
      draft.name = "half done";
      draft.domain.custom = true;
      draft.domain.vesselTypes = "A:\n  length: 3\n";
    });
    first.store.getState().setStep("runs");
    const second = storeWith(first.storage);
    expect(second.store.getState().step).toBe("runs");
    expect(second.store.getState().draft.name).toBe("half done");
    expect(second.store.getState().draft.domain.vesselTypes).toBe("A:\n  length: 3\n");
    expect(second.store.getState().visited).toEqual(["scope"]);
  });

  it("starts over on reset and stores the empty draft", () => {
    const { store, storage } = storeWith();
    store.getState().update((draft) => {
      draft.name = "x";
    });
    store.getState().setStep("policy");
    store.getState().reset();
    expect(store.getState().step).toBe("scope");
    expect(store.getState().draft.name).toBe("");
    expect(JSON.parse(storage.getItem(WIZARD_STORAGE_KEY) as string).state.draft.name).toBe("");
  });

  it("ignores a stored step it does not know", () => {
    const storage = new MemoryStorage();
    storage.setItem(WIZARD_STORAGE_KEY, JSON.stringify({ state: { step: "teleport", draft: { name: "kept" }, visited: ["scope", "bogus"] }, version: 1 }));
    const { store } = storeWith(storage);
    expect(store.getState().step).toBe("scope");
    expect(store.getState().draft.name).toBe("kept");
    expect(store.getState().visited).toEqual(["scope"]);
  });
});

describe("normalizeDraft", () => {
  it("fills the sections a stored draft lacks", () => {
    const draft = normalizeDraft({ name: "old", resources: { priority: 3, queueDepth: { simulate: 8 } }, runs: [{ stackId: "kinematic.replay" }] });
    expect(draft.name).toBe("old");
    expect(draft.resources.priority).toBe(3);
    expect(draft.resources.queueDepth).toMatchObject({ simulate: 8, generate_scene: 16 });
    expect(draft.resources).toMatchObject({ fullUsage: true, nodes: [] });
    expect(draft.runs[0]).toMatchObject({ stackId: "kinematic.replay", monitor: "post_hoc", repeats: 1 });
    expect(draft.trajectories.generator).toBe("monitor_driven_rrt");
  });

  it("gives an empty draft for anything that is not an object", () => {
    expect(normalizeDraft(null).name).toBe(emptyDraft().name);
    expect(normalizeDraft("x").scope).toHaveLength(1);
  });
});
