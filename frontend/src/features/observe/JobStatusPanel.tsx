import { useEffect, useRef } from "react";
import { jobTopic } from "../../domain/cluster/liveProtocol";
import { jobReducer } from "../../domain/cluster/liveTopics";
import { useLiveTopic } from "../../domain/cluster/useLiveTopic";
import { formatClock } from "./formatClock";
import { ProgressBar, StateChip, TopicNotice } from "./StatusParts";

/** A job's status, progress and recent log lines, from its `job:<id>` topic. */
export function JobStatusPanel({ jobId }: { jobId: string | null }) {
  const topic = useLiveTopic(jobId ? jobTopic(jobId) : null, jobReducer);
  const data = topic.data;
  const logRef = useRef<HTMLOListElement | null>(null);
  const stuckToEnd = useRef(true);
  const logCount = data?.logs.length ?? 0;

  useEffect(() => {
    const list = logRef.current;
    if (list && stuckToEnd.current) {
      list.scrollTop = list.scrollHeight;
    }
  }, [logCount]);

  return (
    <section className="observe-card" aria-label="Job status">
      <header className="observe-card-head">
        <h3>Job</h3>
        {data && <StateChip state={data.job.state} />}
        {jobId && (
          <code className="observe-id" title={jobId}>
            {jobId.slice(0, 12)}
          </code>
        )}
      </header>
      {jobId === null && <p className="meta">This instance has no job.</p>}
      <TopicNotice topic={topic} noun="job status" />
      {data && (
        <>
          <dl className="observe-facts">
            <div>
              <dt>Type</dt>
              <dd>{data.job.job_type}</dd>
            </div>
            <div>
              <dt>Attempt</dt>
              <dd>
                {data.job.attempt} of {data.job.max_attempts}
              </dd>
            </div>
            <div>
              <dt>Node</dt>
              <dd>{data.job.lease_owner ?? "none"}</dd>
            </div>
          </dl>
          <ProgressBar progress={data.status?.progress ?? null} label="Job progress" />
          {data.status && (
            <p className="observe-message">
              {data.status.message || "No message."} <span className="meta">at {formatClock(data.status.at)}</span>
            </p>
          )}
          {data.job.error && <p className="observe-notice observe-notice--bad">{data.job.error}</p>}
          <h4 className="observe-subhead">Log</h4>
          {data.logs.length === 0 ? (
            <p className="meta">No log lines yet.</p>
          ) : (
            <ol
              className="observe-log"
              ref={logRef}
              onScroll={(event) => {
                const list = event.currentTarget;
                stuckToEnd.current = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
              }}
            >
              {data.logs.map((line, index) => (
                <li key={`${line.timestamp}-${index}`} className={line.stream === "stderr" ? "observe-log-line observe-log-line--err" : "observe-log-line"}>
                  <span className="observe-log-time">{formatClock(line.timestamp)}</span>
                  <span className="observe-log-source">{line.source}</span>
                  <span className="observe-log-text">{line.text}</span>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
