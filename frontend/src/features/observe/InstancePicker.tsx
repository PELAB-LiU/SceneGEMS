import type { ObservableInstance } from "../../domain/cluster/observableInstances";
import type { NodeView } from "../../domain/cluster/schemas";
import { KindChip, StateChip } from "./StatusParts";

const KIND_LABELS: Record<ObservableInstance["kind"], string> = {
  scene_generation: "scene generation",
  trajectory_generation: "trajectory search",
  simulation: "simulation",
  monitoring: "monitoring",
};

interface InstancePickerProps {
  nodes: NodeView[];
  node: NodeView | null;
  instances: ObservableInstance[];
  jobsLoading: boolean;
  jobsError: string | null;
  selectedTopic: string | null;
  onSelectNode: (nodeId: string) => void;
  onSelectInstance: (instance: ObservableInstance) => void;
}

function InstanceRow({ instance, selected, onSelect }: { instance: ObservableInstance; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button type="button" className={`observe-instance${selected ? " observe-instance--selected" : ""}`} aria-pressed={selected} onClick={onSelect}>
        <span className="observe-instance-label">{instance.label}</span>
        <span className="observe-instance-chips">
          <KindChip>{KIND_LABELS[instance.kind]}</KindChip>
          <StateChip state={instance.state} />
        </span>
      </button>
    </li>
  );
}

/** The node, then its instances: pool instances from its capabilities and slots, then the jobs it holds. */
export function InstancePicker({ nodes, node, instances, jobsLoading, jobsError, selectedTopic, onSelectNode, onSelectInstance }: InstancePickerProps) {
  const pools = instances.filter((entry) => entry.origin === "pool");
  const jobs = instances.filter((entry) => entry.origin === "job");
  return (
    <nav className="observe-picker" aria-label="Instances">
      <h3 className="observe-picker-step">1. Node</h3>
      <ul className="observe-node-list">
        {nodes.map((entry) => (
          <li key={entry.node_id}>
            <button
              type="button"
              className={`observe-node${node?.node_id === entry.node_id ? " observe-node--selected" : ""}`}
              aria-pressed={node?.node_id === entry.node_id}
              onClick={() => onSelectNode(entry.node_id)}
            >
              <span className={`node-dot${entry.connected ? " node-dot--connected" : ""}`} aria-hidden="true" />
              <span className="observe-node-name">
                {entry.name}
                {entry.machine && <span className="meta"> on {entry.machine}</span>}
              </span>
              <StateChip state={entry.status} />
            </button>
          </li>
        ))}
      </ul>

      <h3 className="observe-picker-step">2. Instance</h3>
      {node === null ? (
        <p className="meta">Choose a node.</p>
      ) : (
        <>
          <h4 className="observe-subhead">Pool instances</h4>
          {pools.length === 0 ? (
            <p className="meta">This node offers no scene generation or trajectory search slots.</p>
          ) : (
            <ul className="observe-instance-list">
              {pools.map((entry) => (
                <InstanceRow key={entry.topic} instance={entry} selected={entry.topic === selectedTopic} onSelect={() => onSelectInstance(entry)} />
              ))}
            </ul>
          )}
          <h4 className="observe-subhead">Jobs on this node</h4>
          {jobsError ? (
            <p className="observe-notice observe-notice--warn">{jobsError}</p>
          ) : jobs.length === 0 ? (
            <p className="meta">{jobsLoading ? "Loading the jobs." : "No job is leased or running on this node."}</p>
          ) : (
            <ul className="observe-instance-list">
              {jobs.map((entry) => (
                <InstanceRow key={entry.topic} instance={entry} selected={entry.topic === selectedTopic} onSelect={() => onSelectInstance(entry)} />
              ))}
            </ul>
          )}
        </>
      )}
    </nav>
  );
}
