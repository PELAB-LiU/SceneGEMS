import type { NodeView } from "../../../domain/cluster/schemas";
import { capabilityLabel, nodeProblems } from "../../campaigns/resourcePlan";

/**
 * Whether the selected cluster can run one of the workbench's job types now: the usable nodes
 * (online, up to date) that offer it, judged as the master's scheduler does, and their slots.
 * Without such a node the workbench does not submit the job; it says why instead.
 */

export interface NodesFeedState {
  /** The selected cluster's operator URL, null when no cluster is selected. */
  operatorUrl: string | null;
  nodes: readonly NodeView[];
  loaded: boolean;
  unreachable: boolean;
}

export interface JobTypeResources {
  jobType: string;
  /** Usable nodes that offer the job type. */
  nodes: number;
  /** Their slots for it, and the slots no job holds now. */
  slots: number;
  freeSlots: number;
  /** Why the workbench cannot run the job type now, null when it can. */
  blocker: string | null;
}

export function jobTypeResources(feed: NodesFeedState, jobType: string): JobTypeResources {
  const offering = feed.nodes.filter((node) => (node.capabilities[jobType]?.slots ?? 0) > 0);
  const usable = offering.filter((node) => nodeProblems(node, {}).length === 0);
  const slots = usable.reduce((sum, node) => sum + node.capabilities[jobType].slots, 0);
  const inUse = usable.reduce((sum, node) => sum + Math.min(node.capabilities[jobType].slots, node.capabilities[jobType].slots_in_use), 0);
  return { jobType, nodes: usable.length, slots, freeSlots: slots - inUse, blocker: resourceBlocker(feed, jobType, offering.length, usable.length) };
}

function resourceBlocker(feed: NodesFeedState, jobType: string, offering: number, usable: number): string | null {
  const capability = capabilityLabel(jobType).toLowerCase();
  if (feed.operatorUrl === null) {
    return "No cluster is selected: choose the active cluster in the left pane, since the workbench runs its jobs there.";
  }
  if (usable > 0) {
    return null;
  }
  if (feed.unreachable) {
    return "The active cluster cannot be reached, so nothing can run on it.";
  }
  if (!feed.loaded) {
    return "Looking for the active cluster's machines...";
  }
  if (offering > 0) {
    return `The machines that offer ${capability} are offline, draining or out of date.`;
  }
  return `No machine of the active cluster offers ${capability}.`;
}

/** A short line on what the cluster offers, such as "6 slots on 2 machines, 4 free". */
export function describeResources(resources: JobTypeResources): string {
  if (resources.nodes === 0) {
    return "no machine";
  }
  const machines = `${resources.nodes} machine${resources.nodes === 1 ? "" : "s"}`;
  return `${resources.slots} slot${resources.slots === 1 ? "" : "s"} on ${machines}, ${resources.freeSlots} free`;
}
