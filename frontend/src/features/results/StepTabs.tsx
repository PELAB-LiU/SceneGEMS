import type { CampaignStep } from "../../domain/cluster/schemas";
import { STEP_LABEL } from "./stepViews";

interface StepTabsProps {
  /** The steps the entry executed, in chain order. */
  steps: readonly CampaignStep[];
  shown: CampaignStep;
  onPick: (step: CampaignStep) => void;
}

/** One view per executed step: only the steps the entry ran are offered. */
export function StepTabs({ steps, shown, onPick }: StepTabsProps) {
  return (
    <div className="results-steps" role="tablist" aria-label="Step of the entry">
      {steps.map((step) => (
        <button
          key={step}
          type="button"
          role="tab"
          id={`results-step-${step}`}
          aria-selected={step === shown}
          aria-controls="results-step-panel"
          className={step === shown ? "results-step active" : "results-step"}
          onClick={() => onPick(step)}
        >
          {STEP_LABEL[step]}
        </button>
      ))}
    </div>
  );
}
