import { QueryClient } from "@tanstack/react-query";
import { emptyDraft, type WizardDraft } from "./wizardState";

/** Fixtures of the wizard's component tests (kept apart from the harness components for fast refresh). */

export function draftOf(change: (draft: WizardDraft) => void = () => undefined): WizardDraft {
  const draft = emptyDraft();
  change(draft);
  return draft;
}

export function queryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}
