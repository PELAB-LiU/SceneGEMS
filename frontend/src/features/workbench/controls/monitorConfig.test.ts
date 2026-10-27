import { describe, expect, it } from "vitest";
import { buildInitializeMonitorMessage, canInitializeMonitor } from "./monitorConfig";

describe("live monitor of the interactive simulation", () => {
  it("starts the server's own monitor with the domain's COLREGS constants", () => {
    expect(buildInitializeMonitorMessage("rules: 1")).toEqual({
      type: "initialize_monitor",
      scope: "internal",
      name: "scenario_monitor",
      topic: "waraps/service/virtual/real/scenario_monitor",
      colregsConstraintsContent: "rules: 1",
    });
  });

  it("starts only on a connected broker, once, and with constants", () => {
    expect(canInitializeMonitor("connected", "disconnected", "rules: 1")).toBe(true);
    expect(canInitializeMonitor("disconnected", "disconnected", "rules: 1")).toBe(false);
    expect(canInitializeMonitor("connected", "connected", "rules: 1")).toBe(false);
    expect(canInitializeMonitor("connected", "disconnected", "  ")).toBe(false);
  });
});
