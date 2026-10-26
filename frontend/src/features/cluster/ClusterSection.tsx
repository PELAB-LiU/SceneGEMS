import { useEffect, useState, type ReactNode } from "react";
import "./cluster.css";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useNodesFeed, useNodesStore } from "../../domain/cluster/nodesStore";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { MasterStatus } from "../../domain/cluster/schemas";
import { useLiveChannelStatus } from "../../domain/cluster/useLiveTopic";
import { ClusterListPanel, SSH_TUNNEL_COMMAND } from "./ClusterListPanel";
import { shortHash, summarizeNodes } from "./clusterFormat";
import { NodeCard } from "./NodeCard";
import { useMasterStatus } from "./useMasterStatus";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

const LIVE_LABELS = {
  idle: "idle",
  connecting: "connecting",
  open: "open",
  reconnecting: "reconnecting",
  closed: "closed",
} as const;

function StatTile({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className={`stat-tile${tone ? ` stat-tile--${tone}` : ""}`}>
      <span className="stat-tile-label">{label}</span>
      <span className="stat-tile-value">{value}</span>
      {detail && <span className="stat-tile-detail">{detail}</span>}
    </div>
  );
}

function MasterStatusPanel({ status }: { status: MasterStatus }) {
  const images = Object.entries(status.expected_fingerprints.images).sort(([a], [b]) => a.localeCompare(b));
  const fingerprints = status.expected_fingerprints;
  return (
    <details className="panel master-status-panel">
      <summary>
        <span className="master-status-title">Master {status.master_id}</span>
        <span className="meta">
          release fingerprints {fingerprints.state}
          {images.length > 0 ? ` (${images.length} images)` : ""}, {status.connected_nodes.length} nodes connected
        </span>
      </summary>
      {fingerprints.error && <p className="meta warning">{fingerprints.error}</p>}
      {images.length > 0 ? (
        <table className="master-images">
          <thead>
            <tr>
              <th>Image</th>
              <th>Expected fingerprint</th>
            </tr>
          </thead>
          <tbody>
            {images.map(([image, fingerprint]) => (
              <tr key={image}>
                <td>
                  <code>{image}</code>
                </td>
                <td>
                  <code title={fingerprint}>{shortHash(fingerprint, 16)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="meta">The master lists no expected images yet.</p>
      )}
    </details>
  );
}

function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="section-empty" role="status">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

/** The Cluster section: the selected cluster's master and its nodes as machine resources. */
export function ClusterSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const nodesState = useNodesStore();
  const liveStatus = useLiveChannelStatus(operatorUrl);
  const statusQuery = useMasterStatus(operatorUrl);
  const now = useNow(5_000);

  const nodesOfCluster = nodesState.operatorUrl === operatorUrl;
  const nodes = nodesOfCluster ? nodesState.nodes : [];
  const loaded = nodesOfCluster && nodesState.loaded;
  const statusError = statusQuery.error;
  const unreachable =
    !loaded &&
    ((statusError instanceof OperatorApiError && statusError.unreachable) || (nodesOfCluster && nodesState.unreachable));
  const summary = summarizeNodes(nodes);

  const badges = cluster && (
    <div className="section-badges">
      <span className={`section-badge${statusQuery.isSuccess ? " section-badge--ok" : statusError ? " section-badge--bad" : ""}`}>
        API {statusQuery.isSuccess ? "reachable" : statusError ? "unreachable" : "checking"}
      </span>
      <span className={`section-badge${liveStatus === "open" ? " section-badge--ok" : liveStatus === "reconnecting" ? " section-badge--warn" : ""}`}>
        live channel {LIVE_LABELS[liveStatus]}
      </span>
      {loaded && (
        <span className="section-badge">
          nodes {nodesState.source === "live" && liveStatus === "open" ? "pushed live" : "polled every 5 s"}
        </span>
      )}
    </div>
  );

  let content: ReactNode;
  if (!cluster) {
    content = (
      <EmptyState title="No cluster selected">
        <p className="meta">Add a cluster or select one in the list to see its machines.</p>
      </EmptyState>
    );
  } else if (unreachable) {
    const error = statusError ?? nodesState.error;
    content = (
      <EmptyState title={`Cannot reach ${cluster.name}`}>
        <p className="meta">{error ? describeOperatorError(error) : `No answer from ${cluster.operatorUrl}.`}</p>
        <p className="meta">
          Check that the master runs and that its operator API is reachable at <code>{cluster.operatorUrl}</code>. For a
          remote master, open the tunnel first:
        </p>
        <code className="cluster-hint-command">{SSH_TUNNEL_COMMAND}</code>
        <div>
          <button type="button" onClick={() => void statusQuery.refetch()} disabled={statusQuery.isFetching}>
            {statusQuery.isFetching ? "Trying..." : "Try again"}
          </button>
        </div>
      </EmptyState>
    );
  } else {
    content = (
      <>
        <div className="stat-tiles">
          <StatTile
            label="Nodes"
            value={loaded ? `${summary.online} / ${summary.nodes}` : "..."}
            detail={loaded ? `online; ${summary.draining} draining, ${summary.offline} offline` : "loading"}
            tone={loaded && summary.offline > 0 ? "warn" : undefined}
          />
          <StatTile
            label="Slots in use"
            value={loaded ? `${summary.slotsInUse} / ${summary.slots}` : "..."}
            detail={loaded ? `${summary.leases} leases` : undefined}
          />
          <StatTile
            label="Out of date"
            value={loaded ? String(summary.outOfDate) : "..."}
            detail={summary.outOfDate > 0 ? "images differ from the master's release" : "every node matches the release"}
            tone={summary.outOfDate > 0 ? "bad" : loaded ? "ok" : undefined}
          />
          <StatTile
            label="Connected"
            value={loaded ? `${summary.connected} / ${summary.nodes}` : "..."}
            detail="nodes with a control link"
          />
        </div>
        {statusQuery.data ? (
          <MasterStatusPanel status={statusQuery.data} />
        ) : statusError ? (
          <p className="meta warning">Master status: {describeOperatorError(statusError)}</p>
        ) : null}
        {nodesOfCluster && nodesState.error && loaded && (
          <p className="meta warning">Nodes may be stale: {nodesState.error}</p>
        )}
        {loaded && nodes.length === 0 ? (
          <EmptyState title="No nodes yet">
            <p className="meta">The master has no paired nodes. Nodes appear here once they pair and connect.</p>
          </EmptyState>
        ) : (
          <div className="node-grid">
            {nodes.map((node) => (
              <NodeCard key={node.node_id} node={node} operatorUrl={cluster.operatorUrl} nowMs={now} />
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <SectionFrame title="Cluster" subtitle="The machines of the selected cluster as its resources." actions={badges}>
      <div className="cluster-layout">
        <div className="cluster-main">{content}</div>
        <aside className="cluster-side">
          <ClusterListPanel />
        </aside>
      </div>
    </SectionFrame>
  );
}
