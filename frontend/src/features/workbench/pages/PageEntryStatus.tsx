import "./pages.css";
import type { PageStore } from "./pageStore";
import { useStore } from "zustand";

/**
 * What a page shows of its entries: the latest loaded entry, a run or a followed entry in
 * progress, or why the page is empty (a deleted entry, a failed load).
 */
export function PageEntryStatus({ store }: { store: PageStore }) {
  const loaded = useStore(store, (s) => s.loaded);
  const status = useStore(store, (s) => s.status);
  const message = useStore(store, (s) => s.message);
  const activeEntryId = useStore(store, (s) => s.activeEntryId);

  if (status === "failed" && message) {
    return (
      <p className="error page-entry-status" role="alert">
        {message}
      </p>
    );
  }
  if ((status === "running" || status === "following" || status === "loading") && (message || activeEntryId)) {
    return (
      <p className="meta page-entry-status" role="status">
        {message ?? "Running"}
        {activeEntryId ? ` Entry ${activeEntryId}.` : ""}
      </p>
    );
  }
  if (loaded !== null) {
    return (
      <p className="meta page-entry-status">
        Shows case {loaded.caseId} of entry {loaded.campaignId}
        {loaded.runRecordId !== undefined ? `, run record ${loaded.runRecordId}` : ""}.
      </p>
    );
  }
  return message ? <p className="meta page-entry-status">{message}</p> : null;
}
