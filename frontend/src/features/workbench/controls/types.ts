import type { LoadScenarioOptions } from "../../../domain/simulation/useSimulationWorkflow";
import type { ClientToServerMessage, TrajectoryGenerationParamsWire } from "../../../domain/simulation/wireTypes";
import type { JobTypeResources } from "../cluster/workbenchResources";
import type { SimulationRunPlan } from "../cluster/simulationJobs";

export interface SimulationStreamControls {
  loadScenarioFromFile: (file: File | null, options?: LoadScenarioOptions) => Promise<void>;
  /** @deprecated Use loadScenarioFromFile */
  initializeSimulation: (file: File | null, options?: LoadScenarioOptions) => Promise<void>;
  startSimulation: () => void;
  resetSimulation: () => void;
  setSpeed: (value: number) => void;
  seek: (value: number) => void;
  sendMessage: (message: ClientToServerMessage) => void;
  /** What the active cluster offers for a job type, and why the workbench cannot run it when it cannot. */
  clusterResources: (jobType: string) => JobTypeResources;
  generateTrajectories: (requestId: string, scenarioContent: string, colregsConstraintsContent: string, params: TrajectoryGenerationParamsWire) => void;
  stopTrajectoryGeneration: () => void;
  runSimulationOnCluster: (plan: Extract<SimulationRunPlan, { where: "cluster" }>, colregsConstraintsContent: string) => void;
  stopSimulationOnCluster: () => void;
  setClusterRunSpeed: (speed: number) => void;
}
