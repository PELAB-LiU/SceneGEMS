import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useCallback, useState, type ComponentType } from "react";
import type { Reason } from "./reasons";
import type { StepProps } from "./stepTypes";
import type { WizardDraft } from "./wizardState";
import { queryClient } from "./wizardTestData";

/**
 * Test harness for the wizard's pages: holds a draft the way the store does (a copy changed in
 * place per update) and hands it to a page, so a component test can click and read the result.
 * Only the `*.dom.test.tsx` files import it.
 */

export function StepHarness<Extra extends object>({
  Page,
  initial,
  extra,
  reasons = [],
  onDraft,
}: {
  Page: ComponentType<StepProps & Extra>;
  initial: WizardDraft;
  extra: Extra;
  reasons?: readonly Reason[];
  /** Called with every draft the page leaves behind. */
  onDraft?: (draft: WizardDraft) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const update = useCallback(
    (change: (draft: WizardDraft) => void) =>
      setDraft((current) => {
        const next = JSON.parse(JSON.stringify(current)) as WizardDraft;
        change(next);
        onDraft?.(next);
        return next;
      }),
    [onDraft]
  );
  return <Page draft={draft} update={update} reasons={reasons} {...extra} />;
}

export function WithQueries({ children, client = queryClient() }: { children: React.ReactNode; client?: QueryClient }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
