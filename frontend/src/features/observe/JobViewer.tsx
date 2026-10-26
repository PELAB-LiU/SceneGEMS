import type { ObservableInstance } from "../../domain/cluster/observableInstances";
import { JobStatusPanel } from "./JobStatusPanel";
import { KindChip } from "./StatusParts";

/** A job without a live picture (monitoring, calibration, jobs of the pooled subsystems): status, progress and logs. */
export function JobViewer({ instance }: { instance: ObservableInstance }) {
  const jobId = instance.job?.job_id ?? null;
  return (
    <div className="observe-viewer">
      <header className="observe-viewer-head">
        <div className="observe-viewer-title">
          <h3>{instance.label}</h3>
          <span className="meta">
            {instance.nodeId} / <code>{instance.instance}</code>
          </span>
        </div>
        <div className="observe-viewer-chips">
          <KindChip>{instance.job?.job_type ?? instance.kind}</KindChip>
        </div>
      </header>
      <p className="meta">This job has no live picture, only its status and log.</p>
      <JobStatusPanel jobId={jobId} />
    </div>
  );
}
