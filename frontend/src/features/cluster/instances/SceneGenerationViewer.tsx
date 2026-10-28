import { useMemo } from "react";
import type { ObservableInstance } from "../../../domain/cluster/observableInstances";
import { useObservedInstance } from "../../../domain/cluster/useObservedInstance";
import { EncounterView } from "./encounterView";
import { evaluationFacts, sceneSampleFrames } from "../../../domain/cluster/observeFrames";
import { TopicNotice } from "./StatusParts";
import { ViewerHeader } from "./ViewerHeader";

/** A scene generation pool instance: the latest sample's scene, whether it is valid and final, and a few facts of its evaluation. */
export function SceneGenerationViewer({ instance }: { instance: ObservableInstance }) {
  const { state: topic } = useObservedInstance(instance.topic);
  const sample = topic.data?.sceneSample ?? null;
  const converted = useMemo(() => sceneSampleFrames(sample), [sample]);
  const facts = useMemo(() => evaluationFacts(sample?.evaluation_data), [sample]);

  return (
    <div className="instances-viewer">
      <ViewerHeader instance={instance} topic={topic} />
      <TopicNotice topic={topic} noun="instance" />
      {topic.status === "live" && sample === null && (
        <p className="instances-empty" role="status">
          No sample yet. This instance sends samples while a scene generation request runs on it.
        </p>
      )}
      {sample && (
        <>
          <div className="instances-sample-flags">
            <span className={`instances-flag ${sample.valid ? "instances-flag--ok" : "instances-flag--bad"}`}>{sample.valid ? "valid scene" : "not valid yet"}</span>
            <span className={`instances-flag ${sample.final ? "instances-flag--ok" : "instances-flag--run"}`}>{sample.final ? "final scene" : "search progress"}</span>
            <span className="meta">
              request <code>{sample.request_id}</code>
            </span>
          </div>
          {converted.error && <p className="instances-notice instances-notice--warn">{converted.error}</p>}
          <EncounterView frames={converted.frames} title="Latest scene" />
          {facts.length > 0 && (
            <dl className="instances-facts instances-facts--wide" aria-label="Evaluation data">
              {facts.map((fact) => (
                <div key={fact.label}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </>
      )}
    </div>
  );
}
