import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { createOperatorClient, OperatorApiError } from "../../domain/cluster/operatorApi";
import {
  fetchVerdictPage,
  fetchVerdictSummary,
  type VerdictFilterState,
  type VerdictPaging,
} from "../../domain/cluster/resultsApi";

const CAMPAIGN_LIST_POLL_MS = 15_000;
const CAMPAIGN_DETAIL_POLL_MS = 10_000;
const TABLE_POLL_MS = 10_000;

export function useResultsClient(operatorUrl: string | null) {
  return useMemo(() => (operatorUrl === null ? null : createOperatorClient(operatorUrl)), [operatorUrl]);
}

/** Retry only what can recover: not an unreachable master, not an answer the master gave. */
function retryOnce(failureCount: number, error: unknown): boolean {
  return !(error instanceof OperatorApiError && (error.unreachable || error.kind === "http")) && failureCount < 2;
}

export function useCampaignList(operatorUrl: string | null) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "campaigns"],
    queryFn: ({ signal }) => (client as NonNullable<typeof client>).listCampaigns({ limit: 200 }, signal),
    enabled: client !== null,
    refetchInterval: CAMPAIGN_LIST_POLL_MS,
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

export function useVerdictPage(operatorUrl: string | null, campaignId: string | null, filters: VerdictFilterState, paging: VerdictPaging) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "verdicts", campaignId, filters, paging],
    queryFn: ({ signal }) => fetchVerdictPage(client as NonNullable<typeof client>, campaignId as string, filters, paging, signal),
    enabled: client !== null && campaignId !== null,
    placeholderData: keepPreviousData,
    refetchInterval: TABLE_POLL_MS,
    retry: retryOnce,
  });
}

export function useVerdictSummary(operatorUrl: string | null, campaignId: string | null, filters: VerdictFilterState) {
  const client = useResultsClient(operatorUrl);
  return useQuery({
    queryKey: ["results", operatorUrl, "verdict-summary", campaignId, filters],
    queryFn: ({ signal }) => fetchVerdictSummary(client as NonNullable<typeof client>, campaignId as string, filters, signal),
    enabled: client !== null && campaignId !== null,
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
