import { describe, expect, it } from "vitest";
import { kinematicSimulationSubmission, planSimulationRun, type SimulationSetup, type SimulationVesselSetup } from "./simulationJobs";

function vessel(vesselId: string, overrides: Partial<SimulationVesselSetup> = {}): SimulationVesselSetup {
  return { vesselId, context: "simulation", asvSoftware: "replay", controlLayer: "none", isOwnShip: vesselId === "0", ...overrides };
}

function setup(vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}): SimulationSetup {
  return { simulatorType: "Kinematic", vessels, windVector: [0, 0, 0], waveAmplitude: 0, ...overrides };
}

describe("where a simulation runs", () => {
  it("runs a kinematic replay on the cluster", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1")]))).toMatchObject({ where: "cluster", jobType: "simulation.kinematic", mode: "replay", ownShipId: null });
  });

  it("runs USV Navigation on the own ship on the cluster", () => {
    const plan = planSimulationRun(setup([vessel("0", { asvSoftware: "usv_navigation" }), vessel("1")]));
    expect(plan).toMatchObject({ where: "cluster", mode: "usv_navigation", ownShipId: 0 });
  });

  it("keeps real vessels and Mission Planner in a live session", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { context: "real", controlLayer: "real_vessel" })]))).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(planSimulationRun(setup([vessel("0", { asvSoftware: "mission_planner" })], { simulatorType: "ArduPilot Sim" }))).toMatchObject({ where: "session", reason: expect.stringContaining("Mission Planner") });
  });

  it("runs simulators without a cluster job as a live session", () => {
    expect(planSimulationRun(setup([vessel("0", { controlLayer: "ardupilot" })], { simulatorType: "Gazebo" }))).toMatchObject({ where: "session", reason: expect.stringContaining("Gazebo has no cluster job") });
  });

  it("keeps wind and USV Navigation on a target ship off the cluster", () => {
    expect(planSimulationRun(setup([vessel("0")], { windVector: [1, 0, 0] })).where).toBe("session");
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { asvSoftware: "usv_navigation" })])).where).toBe("session");
  });

  it("builds the kinematic job with the live monitor", () => {
    const plan = planSimulationRun(setup([vessel("0", { asvSoftware: "usv_navigation" }), vessel("1")]));
    if (plan.where !== "cluster") {
      throw new Error("expected a cluster plan");
    }
    const submission = kinematicSimulationSubmission(plan, { scene_list: [] }, "rules");
    expect(submission).toEqual({
      job_type: "simulation.kinematic",
      payload: { mode: "usv_navigation", trajectories: { scene_list: [] }, monitor: "live", colregs_constraints_content: "rules", include_trajectories: true, own_ship_id: 0 },
      max_attempts: 1,
    });
  });
});
