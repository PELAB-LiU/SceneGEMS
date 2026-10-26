import { useMemo } from "react";
import type { ObservableInstance } from "../../domain/cluster/observableInstances";
import { useObservedInstance } from "../../domain/cluster/useObservedInstance";
import { EncounterView } from "./encounterView";
import { trajectoryPreviewFrames } from "./observeFrames";
import { TopicNotice } from "./StatusParts";
import { ViewerHeader } from "./ViewerHeader";

/** A trajectory generation pool instance: the latest search preview's paths over time, and the verdict of the final result. */
export function TrajectoryViewer({ instance }: { instance: ObservableInstance }) {
  const { state: topic } = useObservedInstance(instance.topic);
  const preview = topic.data?.trajectoryPreview ?? null;
  const converted = useMemo(() => trajectoryPreviewFrames(preview), [preview]);
  const timeStep = converted.frames[0]?.timeStep ?? null;

  return (
    <div className="observe-viewer">
      <ViewerHeader instance={instance} topic={topic} />
      <TopicNotice topic={topic} noun="instance" />
      {topic.status === "live" && preview === null && (
        <p className="observe-empty" role="status">
          No preview yet. This instance sends previews while a trajectory search runs on it.
        </p>
      )}
      {preview && (
        <>
          <div className="observe-sample-flags">
            <span className={`observe-flag ${preview.final ? "observe-flag--ok" : "observe-flag--run"}`}>{preview.final ? "final result" : "search preview"}</span>
            {preview.final && preview.valid !== null && preview.valid !== undefined && (
              <span className={`observe-flag ${preview.valid ? "observe-flag--ok" : "observe-flag--bad"}`}>{preview.valid ? "valid" : "not valid"}</span>
            )}
            {preview.final && preview.complete !== null && preview.complete !== undefined && (
              <span className={`observe-flag ${preview.complete ? "observe-flag--ok" : "observe-flag--warn"}`}>
                {preview.complete ? "complete path" : "partial path"}
              </span>
            )}
            <span className="meta">
              request <code>{preview.request_id}</code>, {converted.frames.length} {converted.frames.length === 1 ? "scene" : "scenes"}
            </span>
          </div>
          {preview.final && preview.error_message && <p className="observe-notice observe-notice--bad">{preview.error_message}</p>}
          {converted.error && <p className="observe-notice observe-notice--warn">{converted.error}</p>}
          <EncounterView frames={converted.frames} timeStep={timeStep} title="Planned paths" />
        </>
      )}
    </div>
  );
}
