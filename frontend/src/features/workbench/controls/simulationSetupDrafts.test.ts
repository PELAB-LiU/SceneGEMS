import { describe, expect, it } from "vitest";
import { buildInitialVesselConnectionDrafts } from "./simulationInitConfig";
import { applySetupRequestToDrafts, applySimulationModels } from "./simulationSetupDrafts";
import { useSimulationSetupRequestStore } from "./simulationSetupRequest";

const drafts = buildInitialVesselConnectionDrafts([
  { id: "0", isOwnShip: true },
  { id: "1", isOwnShip: false },
]).map((draft) => ({ ...draft, asvSoftware: "mission_planner" as const, controlLayer: "ardupilot" as const }));

describe("a loaded run's setup", () => {
  it("replays every vessel on the kinematic layer", () => {
    const applied = applySetupRequestToDrafts(drafts, "replay", new Set(["0"]));
    expect(applied.map((draft) => [draft.asvSoftware, draft.controlLayer, draft.context])).toEqual([
      ["replay", "none", "simulation"],
      ["replay", "none", "simulation"],
    ]);
  });

  it("steers the own ship with USV Navigation", () => {
    const applied = applySetupRequestToDrafts(drafts, "usv_navigation", new Set(["0"]));
    expect(applied.map((draft) => draft.asvSoftware)).toEqual(["usv_navigation", "replay"]);
  });

  it("asks again with a new token for the same setup", () => {
    const setup = { simulatorType: "Kinematic" as const, mode: "replay" as const, windVector: [0, 0, 0] as [number, number, number], wave: null };
    useSimulationSetupRequestStore.getState().requestSetup(setup);
    const first = useSimulationSetupRequestStore.getState().request?.token ?? 0;
    useSimulationSetupRequestStore.getState().requestSetup(setup);
    expect(useSimulationSetupRequestStore.getState().request?.token).toBe(first + 1);
  });
});

describe("server vessel models", () => {
  it("go on the vessels they were made for", () => {
    const applied = applySimulationModels(drafts, { "1": "<sdf/>", "0": null });
    expect(applied.map((draft) => draft.gazeboVesselModel)).toEqual([undefined, "<sdf/>"]);
  });
});
