import { useEffect } from "react";
import { PAGE_STORES } from "./pageStore";
import { selectPendingTarget, takeTarget, useWorkbenchTargetStore, type WorkbenchPage, type WorkbenchTarget } from "./workbenchTarget";

/**
 * How the pages take what other sections open on them (`openInWorkbench`): the shown page takes
 * its queued target when it mounts and whenever a new one is queued while it is shown.
 */

/** Takes the page's queued target and opens it; returns it (undefined when none was queued). */
export function consumeTarget(page: WorkbenchPage, open: (target: WorkbenchTarget) => void): WorkbenchTarget | undefined {
  const target = takeTarget(page);
  if (target !== undefined) {
    open(target);
  }
  return target;
}

/** The shown page (null for a view that is no page) takes its targets. `open` should be stable. */
export function useTargetConsumer(page: WorkbenchPage | null, open: (target: WorkbenchTarget) => void): void {
  const pending = useWorkbenchTargetStore((state) => (page === null ? undefined : selectPendingTarget(state, page)));
  useEffect(() => {
    if (page !== null && pending !== undefined) {
      consumeTarget(page, open);
    }
  }, [open, page, pending]);
}

/** The pages' loaded entries, to fetch again from a cluster (the contents are not stored in the browser). */
export function loadedTargets(): WorkbenchTarget[] {
  return Object.values(PAGE_STORES)
    .map((store) => store.getState().loaded)
    .filter((target): target is WorkbenchTarget => target !== null);
}

/**
 * When the workbench mounts and whenever another cluster is selected, every page fetches its
 * loaded entry again: the output shows after a reload, and a page whose entry was deleted
 * meanwhile clears itself. `refresh` should be stable.
 */
export function useLoadedRefresh(operatorUrl: string | null, refresh: (target: WorkbenchTarget) => void): void {
  useEffect(() => {
    if (operatorUrl === null) {
      return;
    }
    for (const target of loadedTargets()) {
      refresh(target);
    }
  }, [operatorUrl, refresh]);
}
