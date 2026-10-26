import type { CampaignTotals } from "../../domain/cluster/schemas";
import { percent, type VerdictSummary } from "../../domain/cluster/resultsApi";
import { formatSeconds } from "./resultsFormat";

interface VerdictSummaryPanelProps {
  summary: VerdictSummary | undefined;
  loading: boolean;
  /** Whether filters narrow the set the summary is about. */
  filtered: boolean;
  campaignTotals: CampaignTotals | undefined;
}

function Tile({ label, count, whole, tone }: { label: string; count: number; whole: number; tone: "passed" | "failed" | "unmonitored" }) {
  return (
    <div className={`results-tile results-tile--${tone}`}>
      <span className="results-tile-label">{label}</span>
      <span className="results-tile-value">{count}</span>
      <span className="results-tile-detail">{whole > 0 ? `${percent(count, whole)} percent` : "none"}</span>
    </div>
  );
}

/** Verdict counts per run and state, and the failed rules ranked by the verdicts they failed in. */
export function VerdictSummaryPanel({ summary, loading, filtered, campaignTotals }: VerdictSummaryPanelProps) {
  if (!summary) {
    return (
      <section className="results-panel" aria-label="Summary of the verdicts">
        <p className="meta" role="status">
          {loading ? "Summarizing the verdicts." : "No summary."}
        </p>
      </section>
    );
  }
  const whole = summary.analyzed;
  const mostFailures = Math.max(1, ...summary.failedRules.map((rule) => rule.verdicts));
  const totals = campaignTotals?.verdicts;
  return (
    <section className="results-panel" aria-label="Summary of the verdicts">
      <header className="results-panel-head">
        <h3>Summary</h3>
        <span className="meta">
          {filtered ? "of the filtered verdicts" : "of all verdicts of the campaign"}
          {summary.partial ? `: the first ${summary.analyzed} of ${summary.total}` : `: ${summary.analyzed}`}
          {summary.sensitive > 0 ? `, ${summary.sensitive} sensitive` : ""}
        </span>
        {loading && <span className="meta" role="status">updating</span>}
        {totals && filtered && (
          <span className="meta results-push">
            whole campaign: {totals.passed ?? 0} passed, {totals.failed ?? 0} failed, {totals.unmonitored ?? 0} unmonitored
          </span>
        )}
      </header>
      {summary.partial && (
        <p className="meta warning">The ranking and the counts below read the first {summary.analyzed} verdicts only; narrow the filters for an exact picture.</p>
      )}
      <div className="results-summary-grid">
        <div className="results-tiles">
          <Tile label="Passed" count={summary.byState.passed} whole={whole} tone="passed" />
          <Tile label="Failed" count={summary.byState.failed} whole={whole} tone="failed" />
          <Tile label="Unmonitored" count={summary.byState.unmonitored} whole={whole} tone="unmonitored" />
        </div>

        <div>
          <h4 className="results-subhead">Per run</h4>
          {summary.byRun.length === 0 ? (
            <p className="meta">No verdicts match.</p>
          ) : (
            <table className="results-table results-table--plain results-table--compact" aria-label="Verdict counts per run and state">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Passed</th>
                  <th>Failed</th>
                  <th>Unmonitored</th>
                  <th>Total</th>
                  <th aria-label="Share failed" />
                </tr>
              </thead>
              <tbody>
                {summary.byRun.map((run) => (
                  <tr key={run.runIndex}>
                    <td>run {run.runIndex}</td>
                    <td className="mono">{run.passed}</td>
                    <td className={`mono${run.failed > 0 ? " results-count-failed" : ""}`}>{run.failed}</td>
                    <td className="mono">{run.unmonitored}</td>
                    <td className="mono">{run.total}</td>
                    <td>
                      <span className="results-bar" title={`${percent(run.failed, run.total)} percent failed`}>
                        <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${percent(run.failed, run.total)}%` }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h4 className="results-subhead">Failed rules, most often first</h4>
          {summary.failedRules.length === 0 ? (
            <p className="meta">No rule failed in these verdicts.</p>
          ) : (
            <ol className="results-rules-rank">
              {summary.failedRules.slice(0, 8).map((rule) => (
                <li key={rule.rule} title={rule.relations.length > 0 ? `vessel pairs: ${rule.relations.join(", ")}` : undefined}>
                  <span className="results-rule-name">{rule.rule}</span>
                  <span className="results-bar">
                    <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${(rule.verdicts / mostFailures) * 100}%` }} />
                  </span>
                  <span className="mono results-rule-count">{rule.verdicts}</span>
                  <span className="meta">earliest {formatSeconds(rule.earliestFailureS)}</span>
                </li>
              ))}
              {summary.failedRules.length > 8 && <li className="meta">and {summary.failedRules.length - 8} more rules</li>}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
