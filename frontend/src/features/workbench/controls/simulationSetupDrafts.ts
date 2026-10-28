import type { VesselInitConnectionDraft } from "./simulationInitConfig";

/** The server's Gazebo vessel models (`simulation_models`) on the vessels they were made for. */
export function applySimulationModels(drafts: VesselInitConnectionDraft[], modelsByVesselId: Record<string, string | null>): VesselInitConnectionDraft[] {
  return drafts.map((draft) => {
    const model = modelsByVesselId[draft.vesselId];
    return model != null ? { ...draft, gazeboVesselModel: model } : draft;
  });
}

/**
 * A loaded kinematic run's stack on the vessel table: every vessel simulated and replaying, and
 * with USV Navigation the own ship steered by it (as `planSimulationRun` plans such a run).
 */
export function applySetupRequestToDrafts(
  drafts: VesselInitConnectionDraft[],
  mode: "replay" | "usv_navigation",
  ownShipIds: ReadonlySet<string>
): VesselInitConnectionDraft[] {
  return drafts.map((draft) => ({
    ...draft,
    context: "simulation",
    asvSoftware: mode === "usv_navigation" && ownShipIds.has(draft.vesselId) ? "usv_navigation" : "replay",
    controlLayer: "none",
  }));
}
