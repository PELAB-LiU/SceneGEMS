import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getFindings, listHistory, type HistoryFilters } from "../../domain/cluster/historyApi";
import { createOperatorClient, OperatorApiError } from "../../domain/cluster/operatorApi";
import {
  fetchVerdictPage,
  fetchVerdictSummary,
  type VerdictFilterState,
  type VerdictPaging,
} from "../../domain/cluster/resultsApi";
import type { CampaignStep, VerdictStep } from "../../domain/cluster/schemas";

const HISTORY_LIST_POLL_MS = 15_000;
const HISTORY_LIST_LIMIT = 200;
const FINDINGS_POLL_MS = 10_000;
const CAMPAIGN_DETAIL_POLL_MS = 10_000;
const TABLE_POLL_MS = 10_000;

export function useResultsClient(operatorUrl: string | null) {
  return useMemo(() => (operatorUrl === null ? null : createOperatorClient(operatorUrl)), [operatorUrl]);
}

/** Retry only what can recover: not an unreachable master, not an answer the master gave. */
function retryOnce(failureCount: number, error: unknown): boolean {
  return !(error instanceof OperatorApiError && (error.unreachable || error.kind === "http")) && failureCount < 2;
}

/** The entries of Campaign History (campaigns and workbench runs, newest first) the picker offers. */
export function useHistoryList(operatorUrl: string | null, filters: Pick<HistoryFilters, "kind" | "q">) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "history", filters.kind ?? null, filters.q ?? ""],
    queryFn: ({ signal }) => listHistory(client as NonNullable<typeof client>, { ...filters, limit: HISTORY_LIST_LIMIT }, signal),
    enabled: client !== null,
    placeholderData: keepPreviousData,
    refetchInterval: HISTORY_LIST_POLL_MS,
    retry: retryOnce,
  });
}

/** The findings of one executed step of an entry; `enabled` is false for a master without the route. */
export function useFindings(operatorUrl: string | null, campaignId: string | null, step: CampaignStep | null, enabled = true) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "findings", campaignId, step],
    queryFn: ({ signal }) => getFindings(client as NonNullable<typeof client>, campaignId as string, step as CampaignStep, signal),
    enabled: enabled && client !== null && campaignId !== null && step !== null,
    refetchInterval: FINDINGS_POLL_MS,
    retry: retryOnce,
  });
}

/** The campaign with its classes: the filter choices and the campaign-wide verdict totals. */
export function useCampaignDetail(operatorUrl: string | null, campaignId: string | null) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "campaign", campaignId],
    queryFn: ({ signal }) => (client as NonNullable<typeof client>).getCampaign(campaignId as string, signal),
    enabled: client !== null && campaignId !== null,
    refetchInterval: CAMPAIGN_DETAIL_POLL_MS,
    retry: retryOnce,
  });
}

export function useVerdictPage(
  operatorUrl: string | null,
  campaignId: string | null,
  filters: VerdictFilterState,
  paging: VerdictPaging,
  step?: VerdictStep
) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "verdicts", campaignId, step ?? null, filters, paging],
    queryFn: ({ signal }) => fetchVerdictPage(client as NonNullable<typeof client>, campaignId as string, filters, paging, signal, step),
    enabled: client !== null && campaignId !== null,
    placeholderData: keepPreviousData,
    refetchInterval: TABLE_POLL_MS,
    retry: retryOnce,
  });
}

export function useVerdictSummary(operatorUrl: string | null, campaignId: string | null, filters: VerdictFilterState, step?: VerdictStep, enabled = true) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "verdict-summary", campaignId, step ?? null, filters],
    queryFn: ({ signal }) => fetchVerdictSummary(client as NonNullable<typeof client>, campaignId as string, filters, signal, undefined, undefined, step),
    enabled: enabled && client !== null && campaignId !== null,
    placeholderData: keepPreviousData,
    refetchInterval: TABLE_POLL_MS * 3,
    retry: retryOnce,
  });
}

export function useCaseDetail(operatorUrl: string | null, campaignId: string | null, caseId: number | null) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "case", campaignId, caseId],
    queryFn: ({ signal }) => (client as NonNullable<typeof client>).getCase(campaignId as string, caseId as number, signal),
    enabled: client !== null && campaignId !== null && caseId !== null,
    refetchInterval: TABLE_POLL_MS,
    retry: retryOnce,
  });
}

/** One job with its recent log lines, fetched while `enabled` (a log panel is open). */
export function useJobDetail(operatorUrl: string | null, jobId: string | null, enabled: boolean) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "job", jobId],
    queryFn: ({ signal }) => (client as NonNullable<typeof client>).getJob(jobId as string, signal),
    enabled: enabled && client !== null && jobId !== null,
    retry: retryOnce,
  });
}
