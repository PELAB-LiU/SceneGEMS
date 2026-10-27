import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { AsvSoftware, ControlLayer, GlobalSimulatorType, SimulationContext } from "../controls/simulationInitConfig";

/**
 * Where a workbench simulation runs. A setup the cluster has a job type for runs there as one
 * job (kinematic replay or USV Navigation on the kinematic layer, judged live by the COLREGS
 * monitor in the job); every other setup is a live session on the master over the MQTT broker:
 * real vessels and Mission Planner are only ever run that way, and the stacks without a
 * cluster job type (ArduPilot, Gazebo, the custom controller) are run that way for now.
 */

export const KINEMATIC_SIMULATION_JOB = "simulation.kinematic";

export interface SimulationVesselSetup {
  vesselId: string;
  context: SimulationContext;
  asvSoftware: AsvSoftware;
  controlLayer: ControlLayer;
  isOwnShip: boolean;
}

export interface SimulationSetup {
  simulatorType: GlobalSimulatorType;
  vessels: SimulationVesselSetup[];
  windVector: [number, number, number];
  waveAmplitude: number;
}

export type SimulationRunPlan =
  | { where: "cluster"; jobType: typeof KINEMATIC_SIMULATION_JOB; mode: "replay" | "usv_navigation"; ownShipId: number | null; summary: string }
  | { where: "session"; reason: string };

function isReplayOnKinematic(vessel: SimulationVesselSetup): boolean {
  return vessel.asvSoftware === "replay" && vessel.controlLayer === "none";
}

export function planSimulationRun(setup: SimulationSetup): SimulationRunPlan {
  const { vessels } = setup;
  if (vessels.some((vessel) => vessel.context === "real")) {
    return { where: "session", reason: "A real vessel joins only a live session over the MQTT broker." };
  }
  if (vessels.some((vessel) => vessel.asvSoftware === "mission_planner")) {
    return { where: "session", reason: "Mission Planner is flown from the desktop in a live session." };
  }
  if (setup.simulatorType !== "Kinematic") {
    return { where: "session", reason: `${setup.simulatorType} has no cluster job yet, so it runs as a live session on the master.` };
  }
  if (setup.windVector.some((component) => component !== 0) || setup.waveAmplitude > 0) {
    return { where: "session", reason: "The kinematic layer has no wind or waves." };
  }
  if (vessels.length === 0) {
    return { where: "session", reason: "Load a scenario first." };
  }
  if (vessels.every(isReplayOnKinematic)) {
    return { where: "cluster", jobType: KINEMATIC_SIMULATION_JOB, mode: "replay", ownShipId: null, summary: "every vessel replays its trajectory" };
  }
  const navigators = vessels.filter((vessel) => !isReplayOnKinematic(vessel));
  const ownShip = navigators[0];
  if (
    navigators.length === 1 &&
    ownShip.isOwnShip &&
    ownShip.asvSoftware === "usv_navigation" &&
    ownShip.controlLayer === "none"
  ) {
    const ownShipId = Number.parseInt(ownShip.vesselId, 10);
    return {
      where: "cluster",
      jobType: KINEMATIC_SIMULATION_JOB,
      mode: "usv_navigation",
      ownShipId: Number.isFinite(ownShipId) ? ownShipId : null,
      summary: "USV Navigation steers the own ship, the others replay",
    };
  }
  return { where: "session", reason: "On the cluster only the own ship may run USV Navigation; this setup runs as a live session." };
}

/** The kinematic job (cluster/node/jobs/simulation_kinematic_job.py) with the COLREGS monitor live, over the loaded trajectories. */
export function kinematicSimulationSubmission(
  plan: Extract<SimulationRunPlan, { where: "cluster" }>,
  trajectories: Record<string, unknown>,
  colregsConstraintsContent: string
): JobSubmission {
  const payload: Record<string, unknown> = {
    mode: plan.mode,
    trajectories,
    monitor: "live",
    colregs_constraints_content: colregsConstraintsContent.trim().length > 0 ? colregsConstraintsContent : null,
    include_trajectories: true,
  };
  if (plan.mode === "usv_navigation" && plan.ownShipId !== null) {
    payload.own_ship_id = plan.ownShipId;
  }
  // A failed run would fail the same way again: the workbench shows it at once.
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}
