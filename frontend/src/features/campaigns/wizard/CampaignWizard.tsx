import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createCampaign } from "../../../domain/cluster/campaignApi";
import { describeOperatorError, OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import { useCatalogClasses, useCatalogStacks, useOperatorClient } from "../useCampaignData";
import { buildCampaignYaml, type BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { DomainStep } from "./DomainStep";
import { PolicyStep } from "./PolicyStep";
import { reasonsByStep, type Reason } from "./reasons";
import { ResourcesStep } from "./ResourcesStep";
import { ReviewStep } from "./ReviewStep";
import { RunsStep } from "./RunsStep";
import { ScopeStep } from "./ScopeStep";
import type { CatalogState, StepProps } from "./stepTypes";
import { TrajectoriesStep } from "./TrajectoriesStep";
import { useValidation, validationFromError } from "./useValidation";
import { useWizardStore, WIZARD_STEP_LABELS, WIZARD_STEPS, type WizardStepId } from "./wizardState";
import "./wizard.css";

const AUTO_CHECK_DELAY_MS = 700;
const EMPTY_BUILDER: BuilderCatalog = { stacks: [], generators: [] };

export interface CampaignWizardProps {
  onClose: () => void;
  onCreated: (campaignId: string) => void;
}

function describeCreateFailure(error: unknown): string {
  if (error instanceof OperatorApiError && error.status === 422) {
    return "The master refused the config. The reasons are listed above.";
  }
  return `The campaign was not created: ${describeOperatorError(error)}`;
}

/** The create wizard: scope, domain, trajectories, runs, resources and policy, then a review that validates the config on the master. */
export function CampaignWizard({ onClose, onCreated }: CampaignWizardProps) {
  const client = useOperatorClient();
  const step = useWizardStore((state) => state.step);
  const draft = useWizardStore((state) => state.draft);
  const visited = useWizardStore((state) => state.visited);
  const setStep = useWizardStore((state) => state.setStep);
  const update = useWizardStore((state) => state.update);
  const reset = useWizardStore((state) => state.reset);

  const classes = useCatalogClasses();
  const stacks = useCatalogStacks();
  const catalogState: CatalogState = {
    classes: classes.data?.items,
    classesError: classes.error,
    classesLoading: classes.isLoading,
    stacks: stacks.data,
    stacksError: stacks.error,
    stacksLoading: stacks.isLoading,
    retry: () => {
      void classes.refetch();
      void stacks.refetch();
    },
  };

  const builderCatalog = useMemo<BuilderCatalog>(
    () => (stacks.data ? { stacks: stacks.data.stacks, generators: stacks.data.trajectory_generators } : EMPTY_BUILDER),
    [stacks.data]
  );
  const yaml = useMemo(() => buildCampaignYaml(draft, builderCatalog), [draft, builderCatalog]);
  const localReasons = useMemo(() => checkDraft(draft, stacks.data ? builderCatalog : null), [draft, builderCatalog, stacks.data]);

  const { state: validation, check, adopt, reset: resetValidation } = useValidation(client);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  // A run without a stack takes the first one the master can run
  useEffect(() => {
    const first = stacks.data?.stacks.find((entry) => entry.available);
    if (first && draft.runs.some((run) => run.stackId === "")) {
      update((next) => {
        for (const run of next.runs) {
          if (run.stackId === "") {
            run.stackId = first.id;
          }
        }
      });
    }
  }, [stacks.data, draft.runs, update]);

  // On the review step the master checks the config as soon as it is complete and has stopped changing
  useEffect(() => {
    if (step !== "review" || localReasons.length > 0 || !client || validation.yaml === yaml) {
      return undefined;
    }
    const timer = setTimeout(() => void check(yaml), AUTO_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [step, localReasons.length, client, validation.yaml, yaml, check]);

  const creation = useMutation({
    mutationFn: ({ start, target }: { start: boolean; target: OperatorClient }) => createCampaign(target, yaml, { start }),
    onSuccess: (campaign) => {
      reset();
      resetValidation();
      setCreateMessage(null);
      onCreated(campaign.campaign_id);
    },
    onError: (error) => {
      adopt(validationFromError(yaml, error));
      setCreateMessage(describeCreateFailure(error));
    },
  });

  const serverReasons: Reason[] = validation.reasons;
  const allReasons = useMemo(() => [...localReasons, ...serverReasons], [localReasons, serverReasons]);
  const byStep = useMemo(() => reasonsByStep(allReasons), [allReasons]);
  // What the browser finds wrong shows on a step once the operator has been through it; the master's reasons always show
  const stepReasons = byStep[step].filter((reason) => reason.source === "server" || visited.includes(step));
  const index = WIZARD_STEPS.indexOf(step);

  const stepProps: StepProps = { draft, update, reasons: stepReasons };
  let body;
  switch (step) {
    case "scope":
      body = <ScopeStep {...stepProps} catalog={catalogState} />;
      break;
    case "domain":
      body = <DomainStep {...stepProps} />;
      break;
    case "trajectories":
      body = <TrajectoriesStep {...stepProps} catalog={catalogState} />;
      break;
    case "runs":
      body = <RunsStep {...stepProps} catalog={catalogState} />;
      break;
    case "resources":
      body = <ResourcesStep {...stepProps} />;
      break;
    case "policy":
      body = <PolicyStep {...stepProps} />;
      break;
    default:
      body = (
        <ReviewStep
          yaml={yaml}
          validation={validation}
          current={validation.yaml === yaml}
          localReasons={localReasons}
          serverReasons={serverReasons}
          onGoTo={setStep}
          onCheck={() => void check(yaml)}
          onCreate={(start) => {
            if (client) {
              setCreateMessage(null);
              creation.mutate({ start, target: client });
            }
          }}
          creating={creation.isPending}
          createMessage={createMessage}
        />
      );
  }

  const stepBadge = (id: WizardStepId): number => {
    const server = byStep[id].filter((reason) => reason.source === "server").length;
    const local = visited.includes(id) ? byStep[id].filter((reason) => reason.source === "local").length : 0;
    return id === "review" ? 0 : server + local;
  };

  return (
    <div className="wiz">
      <header className="wiz-head panel">
        <div>
          <h3>New campaign</h3>
          <p className="meta">Your entries are kept in this browser until the campaign is created or you discard them.</p>
        </div>
        <div className="wiz-head-actions">
          <button type="button" onClick={onClose}>
            Close, keep the draft
          </button>
          <button
            type="button"
            className="wiz-remove"
            onClick={() => {
              if (window.confirm("Discard everything entered in the wizard?")) {
                reset();
                resetValidation();
                setCreateMessage(null);
              }
            }}
          >
            Discard the draft
          </button>
        </div>
      </header>
      <nav className="wiz-steps" aria-label="Wizard steps">
        <ol>
          {WIZARD_STEPS.map((id, at) => {
            const count = stepBadge(id);
            return (
              <li key={id}>
                <button type="button" className={`wiz-step-tab${id === step ? " wiz-step-tab--on" : ""}${count > 0 ? " wiz-step-tab--bad" : ""}`} aria-current={id === step ? "step" : undefined} onClick={() => setStep(id)}>
                  <span className="wiz-step-number">{at + 1}</span>
                  <span className="wiz-step-label">{WIZARD_STEP_LABELS[id]}</span>
                  {count > 0 && (
                    <span className="wiz-step-count" title={`${count} ${count === 1 ? "problem" : "problems"}`}>
                      {count}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
      <div className="wiz-body panel">{body}</div>
      <footer className="wiz-foot">
        <button type="button" disabled={index === 0} onClick={() => setStep(WIZARD_STEPS[index - 1])}>
          Back
        </button>
        {step !== "review" && (
          <>
            <button type="button" className="primary-btn accent" onClick={() => setStep(WIZARD_STEPS[index + 1])}>
              Next: {WIZARD_STEP_LABELS[WIZARD_STEPS[index + 1]]}
            </button>
            <button type="button" onClick={() => setStep("review")}>
              Review the config
            </button>
          </>
        )}
      </footer>
    </div>
  );
}
