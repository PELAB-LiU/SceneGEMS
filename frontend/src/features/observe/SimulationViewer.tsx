import { useMemo, useState } from "react";
import { INSTANCE_FRAMES_KEPT } from "../../domain/cluster/liveTopics";
import type { ObservableInstance } from "../../domain/cluster/observableInstances";
import { useObservedInstance } from "../../domain/cluster/useObservedInstance";
import { EncounterView } from "./encounterView";
import { JobStatusPanel } from "./JobStatusPanel";
import { FrameBuffer } from "./observeFrames";
import { SpeedControl } from "./SpeedControl";
import { DEFAULT_OBSERVED_SPEED } from "./speedChoices";
import { TopicNotice } from "./StatusParts";
import { ViewerHeader } from "./ViewerHeader";

const RUNNING_STATES = new Set(["leased", "running"]);

/**
 * A simulation job's instance: the job's status, progress and logs, the pace control, and the
 * live frames of the run in the encounter view. Opening the view subscribes with the default
 * pace; each choice afterwards is sent as `configure`.
 */
export function SimulationViewer({ instance }: { instance: ObservableInstance }) {
  const [requested, setRequested] = useState(DEFAULT_OBSERVED_SPEED);
  const { state: topic, configure } = useObservedInstance(instance.topic, { speed: DEFAULT_OBSERVED_SPEED });
  const [buffer] = useState(() => new FrameBuffer(INSTANCE_FRAMES_KEPT));
  const data = topic.data;
  const frames = useMemo(() => (data ? buffer.sync(data.frames, data.frameCount) : []), [buffer, data]);
  const running = data ? RUNNING_STATES.has(data.state) : false;
  const jobId = data?.info.job_id ?? instance.job?.job_id ?? null;

  return (
    <div className="observe-viewer">
      <ViewerHeader instance={instance} topic={topic} />
      <TopicNotice topic={topic} noun="instance" />
      <SpeedControl
        requested={requested}
        reported={data?.info.observed_speed}
        disabled={topic.status !== "live"}
        onChange={(speed) => {
          setRequested(speed);
          configure({ speed });
        }}
      />
      <EncounterView frames={frames} live={running} timeStep={frames[0]?.timeStep ?? null} title="Live run" />
      {topic.status === "live" && frames.length === 0 && (
        <p className="observe-empty" role="status">
          {running ? "Waiting for the first frames of the run." : "No frames. A run sends frames only while it executes and someone watches."}
        </p>
      )}
      {data && (
        <p className="meta">
          {data.frameCount} frames received{buffer.skippedCount > 0 ? `, ${buffer.skippedCount} could not be read` : ""}.
        </p>
      )}
      <JobStatusPanel jobId={jobId} />
    </div>
  );
}
