import { useRef, useState } from "react";
import "./pages.css";
import { describeOperatorError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { fetchArtifact } from "./entryLoader";
import { HistoryOutputPicker } from "./HistoryOutputPicker";
import { inputOfHistoryOutput } from "./pageHandoff";
import type { PageInput } from "./pageStore";

const ORIGIN_TEXT: Record<PageInput["origin"], string> = {
  previous_page: "from the previous page",
  history: "from Campaign History",
  file: "from a file",
};

interface Props {
  /** What the page calls its input, such as "Input scene". */
  title: string;
  input: PageInput | null;
  /** Shown while the page has no input. */
  emptyText: string;
  /** The one-click button for the previous page's output. */
  previousLabel: string;
  previousAvailable: boolean;
  onUsePrevious: () => void;
  /** The step of Campaign History whose outputs the page takes. */
  historyStep: CampaignStep;
  /** The active cluster's operator client, null without one (no history then). */
  client: OperatorClient | null;
  /** A history output was picked: its input and its content as the master stores it. */
  onPickHistory: (input: PageInput, document: unknown) => void | Promise<void>;
  onPickFile: (file: File) => void | Promise<void>;
  disabled?: boolean;
}

/**
 * The input of a workbench page and the three ways to set it: the previous page's output in one
 * click, an output in Campaign History, or a file. A new run uses this input.
 */
export function PageInputPanel({ title, input, emptyText, previousLabel, previousAvailable, onUsePrevious, historyStep, client, onPickHistory, onPickFile, disabled = false }: Props) {
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const run = async (work: () => Promise<void> | void) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      setError(describeOperatorError(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page-input" aria-label={title}>
      <p className={`meta page-input-line${input ? " is-ok" : ""}`} role="status">
        <span className="page-input-title">{title}:</span>{" "}
        {input ? (
          <>
            {input.label} <span className="page-input-origin">({ORIGIN_TEXT[input.origin]})</span>
          </>
        ) : (
          emptyText
        )}
      </p>
      <div className="toolbar-row page-input-actions">
        <button type="button" disabled={disabled || busy || !previousAvailable} onClick={() => void run(onUsePrevious)}>
          {previousLabel}
        </button>
        <button type="button" disabled={disabled || busy || client === null} aria-expanded={picking} title={client === null ? "Select a cluster to use its Campaign History" : undefined} onClick={() => setPicking(!picking)}>
          From Campaign History
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) {
              void run(() => onPickFile(file));
            }
          }}
        />
        <button type="button" disabled={disabled || busy} onClick={() => fileInputRef.current?.click()}>
          From a file...
        </button>
      </div>
      {busy ? <p className="meta">Loading the input...</p> : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {picking && client !== null ? (
        <HistoryOutputPicker
          client={client}
          step={historyStep}
          onClose={() => setPicking(false)}
          onPick={(entry, row) => {
            const picked = inputOfHistoryOutput(entry, row, historyStep);
            if (picked === null || picked.ref === null) {
              return;
            }
            const sha = picked.ref.sha256;
            setPicking(false);
            void run(async () => {
              const { document } = await fetchArtifact(client, sha);
              await onPickHistory(picked, document);
            });
          }}
        />
      ) : null}
    </section>
  );
}
