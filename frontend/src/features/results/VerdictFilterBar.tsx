import { hasActiveFilters, runIndexesOf, type SensitiveFilter, type VerdictFilterState } from "../../domain/cluster/resultsApi";
import type { CampaignDetail, VerdictState } from "../../domain/cluster/schemas";

interface VerdictFilterBarProps {
  detail: CampaignDetail | undefined;
  filters: VerdictFilterState;
  onChange: (changes: Partial<VerdictFilterState>) => void;
  onReset: () => void;
  /** The CSV download of the filtered set. */
  csvUrl: string | null;
  total: number | null;
}

export function VerdictFilterBar({ detail, filters, onChange, onReset, csvUrl, total }: VerdictFilterBarProps) {
  const classes = (detail?.classes ?? []).map((view) => view.class_id).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const runs = runIndexesOf(detail);
  const active = hasActiveFilters(filters);
  return (
    <section className="results-filters" aria-label="Filters">
      <label className="results-field results-field--wide">
        <span>Class</span>
        <select value={filters.classId} onChange={(event) => onChange({ classId: event.target.value })}>
          <option value="">All classes ({classes.length})</option>
          {filters.classId !== "" && !classes.includes(filters.classId) && <option value={filters.classId}>{filters.classId}</option>}
          {classes.map((classId) => (
            <option key={classId} value={classId}>
              {classId}
            </option>
          ))}
        </select>
      </label>
      <label className="results-field">
        <span>Verdict</span>
        <select value={filters.state} onChange={(event) => onChange({ state: event.target.value as VerdictState | "any" })}>
          <option value="any">Any</option>
          <option value="passed">Passed</option>
          <option value="failed">Failed</option>
          <option value="unmonitored">Unmonitored</option>
        </select>
      </label>
      <label className="results-field">
        <span>Run</span>
        <select value={filters.runIndex === null ? "" : String(filters.runIndex)} onChange={(event) => onChange({ runIndex: event.target.value === "" ? null : Number(event.target.value) })}>
          <option value="">Any</option>
          {filters.runIndex !== null && !runs.includes(filters.runIndex) && <option value={filters.runIndex}>run {filters.runIndex}</option>}
          {runs.map((run) => (
            <option key={run} value={run}>
              run {run}
            </option>
          ))}
        </select>
      </label>
      <label className="results-field">
        <span>Sensitive</span>
        <select value={filters.sensitive} onChange={(event) => onChange({ sensitive: event.target.value as SensitiveFilter })}>
          <option value="any">Any</option>
          <option value="yes">Only sensitive</option>
          <option value="no">Not sensitive</option>
        </select>
      </label>
      <div className="results-filter-actions">
        <button type="button" onClick={onReset} disabled={!active}>
          Clear filters
        </button>
        {csvUrl ? (
          <a className="results-csv" href={csvUrl} download title="Every verdict the filters match, as CSV, in the table's columns plus the case id">
            Download CSV{total !== null ? ` (${total})` : ""}
          </a>
        ) : (
          <span className="meta">CSV unavailable</span>
        )}
      </div>
    </section>
  );
}
