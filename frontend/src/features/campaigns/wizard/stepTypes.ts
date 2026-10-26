import type { CatalogClass, CatalogStacks } from "../../../domain/cluster/campaignApi";
import type { Reason } from "./reasons";
import type { WizardDraft } from "./wizardState";

/** What every step of the wizard receives. */
export interface StepProps {
  draft: WizardDraft;
  /** Applies a change to the draft (a copy to edit in place). */
  update: (change: (draft: WizardDraft) => void) => void;
  /** The reasons that belong to this step: the master's and the browser's. */
  reasons: readonly Reason[];
}

export interface CatalogState {
  classes: readonly CatalogClass[] | undefined;
  classesError: unknown;
  classesLoading: boolean;
  stacks: CatalogStacks | undefined;
  stacksError: unknown;
  stacksLoading: boolean;
  retry: () => void;
}
