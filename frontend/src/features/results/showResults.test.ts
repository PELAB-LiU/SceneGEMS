import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../test/memoryStorage";

// uiStore's persist takes window.localStorage when the store is created, so the modules load after the stubs.
const storage = new MemoryStorage();
let show: typeof import("./showResults");
let ui: typeof import("../../app/uiStore");
let results: typeof import("../../domain/cluster/resultsStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  ui = await import("../../app/uiStore");
  results = await import("../../domain/cluster/resultsStore");
  show = await import("./showResults");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("showing results from another section", () => {
  beforeEach(() => {
    storage.clear();
    ui.useUiStore.getState().setSection("campaigns");
    results.useResultsStore.getState().reset();
  });

  it("opens a campaign's verdicts and shows the Results section", () => {
    show.showCampaignResults("c7");
    expect(ui.useUiStore.getState().section).toBe("results");
    expect(results.useResultsStore.getState()).toMatchObject({ campaignId: "c7", caseId: null });
  });

  it("opens a workbench entry on the step view asked for", () => {
    show.showCampaignResults("wb1", "trajectory_generation");
    expect(ui.useUiStore.getState().section).toBe("results");
    expect(results.useResultsStore.getState()).toMatchObject({ campaignId: "wb1", step: "trajectory_generation", caseId: null });
  });

  it("opens one case of a campaign", () => {
    show.showCaseResults("c7", 42);
    expect(ui.useUiStore.getState().section).toBe("results");
    expect(results.useResultsStore.getState()).toMatchObject({ campaignId: "c7", caseId: 42 });
  });

  it("opens one case on a step", () => {
    show.showCaseResults("c7", 42, "scene_generation");
    expect(results.useResultsStore.getState()).toMatchObject({ campaignId: "c7", caseId: 42, step: "scene_generation" });
  });
});
