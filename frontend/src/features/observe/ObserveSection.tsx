import { useMemo, useState } from "react";
import "./observe.css";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useNodesFeed, useNodesStore } from "../../domain/cluster/nodesStore";
import { nodeInstances, viewerFor, type ObservableInstance } from "../../domain/cluster/observableInstances";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import { useLiveChannelStatus } from "../../domain/cluster/useLiveTopic";
import { InstancePicker } from "./InstancePicker";
import { InstanceViewer } from "./InstanceViewer";
import { useNodeJobs } from "./useNodeJobs";

/**
 * The Observe section: node, then instance, then its viewer. Only the viewed instance is
 * subscribed; changing the instance or leaving the section ends the subscription, and with
 * it the master's observation of that instance.
 */
export function ObserveSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const nodesState = useNodesStore();
  const liveStatus = useLiveChannelStatus(operatorUrl);
  const [chosenNodeId, setChosenNodeId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ObservableInstance | null>(null);

  const nodes = nodesState.operatorUrl === operatorUrl ? nodesState.nodes : [];
  const loaded = nodesState.operatorUrl === operatorUrl && nodesState.loaded;
  const node = nodes.find((entry) => entry.node_id === chosenNodeId) ?? (nodes.length === 1 ? nodes[0] : null);
  const jobsQuery = useNodeJobs(operatorUrl, node);
  const instances = useMemo(() => (node ? nodeInstances(node, jobsQuery.data ?? []) : []), [node, jobsQuery.data]);
  const viewed = selected && node && selected.nodeId === node.node_id ? selected : null;

  const badges = cluster && (
    <div className="section-badges">
      <span className={`section-badge${liveStatus === "open" ? " section-badge--ok" : liveStatus === "reconnecting" ? " section-badge--warn" : ""}`}>
        live channel {liveStatus}
      </span>
      {viewed && (
        <span className="section-badge section-badge--ok">
          {viewerFor(viewed) === "job" ? "following" : "observing"} {viewed.instance}
        </span>
      )}
    </div>
  );

  return (
    <SectionFrame title="Observe" subtitle="Follow one subsystem instance of the cluster live. The master observes an instance only while you view it." actions={badges}>
      {!cluster ? (
        <div className="section-empty" role="status">
          <h3>No cluster selected</h3>
          <p className="meta">Select or add a cluster in the left pane to observe its instances.</p>
        </div>
      ) : !loaded ? (
        <div className="section-empty" role="status">
          <h3>{nodesState.unreachable ? "The master is not reachable" : "Loading the nodes"}</h3>
          <p className="meta">{nodesState.error ?? "The nodes of the cluster arrive in a moment."}</p>
        </div>
      ) : nodes.length === 0 ? (
        <div className="section-empty" role="status">
          <h3>No nodes in this cluster</h3>
          <p className="meta">Instances appear once a node has registered with the master.</p>
        </div>
      ) : (
        <div className="observe-layout">
          <InstancePicker
            nodes={nodes}
            node={node}
            instances={instances}
            jobsLoading={jobsQuery.isPending}
            jobsError={jobsQuery.error ? describeOperatorError(jobsQuery.error) : null}
            selectedTopic={viewed?.topic ?? null}
            onSelectNode={(nodeId) => {
              setChosenNodeId(nodeId);
              setSelected(null);
            }}
            onSelectInstance={setSelected}
          />
          <div className="observe-stage">
            {viewed ? (
              <>
                <div className="observe-stage-bar">
                  <button type="button" onClick={() => setSelected(null)}>
                    Close the view
                  </button>
                </div>
                <InstanceViewer key={viewed.topic} instance={viewed} />
              </>
            ) : (
              <div className="section-empty" role="status">
                <h3>Nothing observed</h3>
                <p className="meta">
                  Choose a node and an instance. Scene generation and trajectory search instances show their latest sample or preview, a simulation shows its
                  frames at a pace you choose, and other jobs show their status and log.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </SectionFrame>
  );
}
