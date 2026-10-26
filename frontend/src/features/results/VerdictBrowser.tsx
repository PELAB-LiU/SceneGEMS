import { useMemo } from "react";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import { hasActiveFilters, toApiFilters, type VerdictPaging } from "../../domain/cluster/resultsApi";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import type { Verdict } from "../../domain/cluster/schemas";
import { VerdictFilterBar } from "./VerdictFilterBar";
import { VerdictSummaryPanel } from "./VerdictSummaryPanel";
import { VerdictTable } from "./VerdictTable";
import { useCampaignDetail, useResultsClient, useVerdictPage, useVerdictSummary } from "./useResultsData";

/** The verdicts of one campaign: filters, a summary and the paged table. */
export function VerdictBrowser({ operatorUrl, campaignId }: { operatorUrl: string; campaignId: string }) {
  const filters = useResultsStore((state) => state.filters);
  const page = useResultsStore((state) => state.page);
  const pageSize = useResultsStore((state) => state.pageSize);
  const direction = useResultsStore((state) => state.direction);
  const { setFilters, resetFilters, setPage, setPageSize, setDirection, openCase } = useResultsStore.getState();

  const paging = useMemo<VerdictPaging>(() => ({ page, pageSize, direction }), [page, pageSize, direction]);
  const client = useResultsClient(operatorUrl);
  const detail = useCampaignDetail(operatorUrl, campaignId);
  const verdicts = useVerdictPage(operatorUrl, campaignId, filters, paging);
  const summary = useVerdictSummary(operatorUrl, campaignId, filters);
  const total = verdicts.data?.total ?? null;
  const csvUrl = client ? client.verdictsCsvUrl(campaignId, toApiFilters(filters)) : null;

  const open = (verdict: Verdict) => openCase(campaignId, verdict.case_id);

  return (
    <div className="results-stack">
      <VerdictFilterBar detail={detail.data} filters={filters} onChange={setFilters} onReset={resetFilters} csvUrl={csvUrl} total={total} />
      <VerdictSummaryPanel
        summary={summary.data}
        loading={summary.isFetching}
        filtered={hasActiveFilters(filters)}
        campaignTotals={detail.data?.totals}
      />
      {summary.isError && <p className="error">The summary could not be loaded: {describeOperatorError(summary.error)}</p>}
      {verdicts.isError ? (
        <div className="results-notice results-notice--bad" role="alert">
          <strong>The verdicts cannot be loaded.</strong>
          <span>{describeOperatorError(verdicts.error)}</span>
        </div>
      ) : (
        <VerdictTable
          verdicts={verdicts.data?.items ?? []}
          total={total}
          paging={paging}
          loading={verdicts.isFetching}
          onOpenCase={open}
          onPage={(next) => setPage(next, total)}
          onPageSize={setPageSize}
          onDirection={setDirection}
        />
      )}
    </div>
  );
}
