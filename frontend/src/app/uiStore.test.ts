import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../test/memoryStorage";

// zustand's persist takes window.localStorage when the store is created, so the module loads after the stubs.
const storage = new MemoryStorage();
let ui: typeof import("./uiStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  ui = await import("./uiStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function migrate(persisted: unknown, version: number) {
  const run = ui.useUiStore.persist.getOptions().migrate;
  if (!run) {
    throw new Error("uiStore has no migrate");
  }
  return run(persisted, version) as Record<string, unknown>;
}

describe("uiStore sections", () => {
  beforeEach(() => {
    storage.clear();
  });

  it("moves the workbench view out of its old key when migrating to v4", () => {
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("sceneGeneration"));
    const state = migrate({ controlPanelMode: "simulation", sceneViewMode: "nautical" }, 3);
    expect(state.section).toBe("workbench");
    expect(state.workbenchView).toBe("sceneGeneration");
    expect(state.controlPanelMode).toBe("simulation");
    expect(state.sceneViewMode).toBe("nautical");
  });

  it("falls back to the simulation view without a valid old key", () => {
    expect(migrate({}, 3).workbenchView).toBe("simulation");
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("monitor"));
    expect(migrate({}, 3).workbenchView).toBe("simulation");
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, "{not json");
    expect(ui.readLegacyWorkbenchView()).toBeNull();
  });

  it("still applies the v2 migration of the monitor control panel mode", () => {
    const state = migrate({ controlPanelMode: "monitor" }, 1);
    expect(state.controlPanelMode).toBe("animation");
    expect(state.section).toBe("workbench");
  });

  it("keeps a v4 state as it is", () => {
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("waraps"));
    const state = migrate({ section: "cluster", workbenchView: "domainConfig" }, 4);
    expect(state).toEqual({ section: "cluster", workbenchView: "domainConfig" });
  });

  it("takes the workbench view from the old key when there is no stored ui state", async () => {
    vi.resetModules();
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("domainConfig"));
    const fresh = await import("./uiStore");
    expect(fresh.useUiStore.getState().workbenchView).toBe("domainConfig");
    expect(fresh.useUiStore.getState().section).toBe("workbench");
  });

  it("persists the section and the workbench view", () => {
    const partialize = ui.useUiStore.persist.getOptions().partialize;
    if (!partialize) {
      throw new Error("uiStore has no partialize");
    }
    ui.useUiStore.getState().setSection("observe");
    ui.useUiStore.getState().setWorkbenchView("trajectoryGeneration");
    const persisted = partialize(ui.useUiStore.getState()) as Record<string, unknown>;
    expect(persisted.section).toBe("observe");
    expect(persisted.workbenchView).toBe("trajectoryGeneration");
    expect(ui.useUiStore.persist.getOptions().version).toBe(4);
  });
});
