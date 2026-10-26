import { Field, FieldIssues, NumberField } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import type { StepProps } from "./stepTypes";
import { QUEUE_DEPTH_DEFAULTS, QUEUE_DEPTH_LABELS } from "./wizardState";

/** Resources: the node labels every job needs, how many jobs of each stage may queue, and the base priority. */
export function ResourcesStep({ draft, update, reasons }: StepProps) {
  const { resources } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), ["required_labels", "queue_depth", "priority"]);

  return (
    <div className="wiz-step">
      <section className="wiz-card" aria-label="Required labels">
        <h4>Required node labels</h4>
        <p className="meta">Every job of the campaign runs only on nodes that carry all of these labels (for example site: lab). Leave it empty to use any node.</p>
        {resources.labels.map((label, index) => (
          <div key={index} className="wiz-map-row">
            <input
              type="text"
              value={label.key}
              placeholder="label"
              aria-label={`Label ${index + 1} name`}
              onChange={(event) => update((next) => void (next.resources.labels[index].key = event.target.value))}
            />
            <input
              type="text"
              value={label.value}
              placeholder="value"
              aria-label={`Label ${index + 1} value`}
              onChange={(event) => update((next) => void (next.resources.labels[index].value = event.target.value))}
            />
            <button type="button" onClick={() => update((next) => void (next.resources.labels = next.resources.labels.filter((_item, at) => at !== index)))}>
              Remove
            </button>
          </div>
        ))}
        <div>
          <button type="button" className="wiz-add" onClick={() => update((next) => void next.resources.labels.push({ key: "", value: "" }))}>
            Add a label
          </button>
        </div>
        <FieldIssues reasons={own.byField.get("required_labels")} />
      </section>

      <section className="wiz-card" aria-label="Queue depth">
        <h4>Queue depth per stage</h4>
        <p className="meta">A new case starts only while every stage has fewer queued jobs of this campaign than its cap. Smaller caps keep the campaign from flooding the cluster.</p>
        <div className="wiz-row">
          {Object.entries(QUEUE_DEPTH_LABELS).map(([stage, label]) => (
            <Field
              key={stage}
              label={label}
              htmlFor={`depth-${stage}`}
              hint={`Default ${QUEUE_DEPTH_DEFAULTS[stage]}.`}
              issues={own.byField.get("queue_depth")?.filter((reason) => reason.field === `queue_depth.${stage}`)}
            >
              <NumberField
                id={`depth-${stage}`}
                integer
                min={1}
                value={resources.queueDepth[stage] ?? null}
                placeholder={String(QUEUE_DEPTH_DEFAULTS[stage])}
                onChange={(value) => update((next) => void (next.resources.queueDepth[stage] = value))}
              />
            </Field>
          ))}
        </div>
        <FieldIssues reasons={own.byField.get("queue_depth")?.filter((reason) => reason.field === "queue_depth")} />
      </section>

      <Field label="Priority" htmlFor="wiz-priority" hint="Base priority of the campaign's jobs. Later stages run above it, so a higher value moves the whole campaign ahead of others." issues={own.byField.get("priority")}>
        <NumberField id="wiz-priority" integer value={resources.priority} invalid={own.byField.has("priority")} onChange={(value) => update((next) => void (next.resources.priority = value))} />
      </Field>
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
