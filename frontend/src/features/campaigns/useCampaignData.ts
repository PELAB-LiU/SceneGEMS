import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { getCatalogStacks, listCatalogClasses } from "../../domain/cluster/campaignApi";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { campaignTopic } from "../../domain/cluster/liveProtocol";
import { campaignReducer, type CampaignTopicState } from "../../domain/cluster/liveTopics";
import { useNodesFeed, useNodesStore } from "../../domain/cluster/nodesStore";
import { createOperatorClient, OperatorApiError, type CampaignControl, type OperatorClient } from "../../domain/cluster/operatorApi";
import type { CampaignConfig, CampaignDetail, CampaignSummary } from "../../domain/cluster/schemas";
import { useLiveTopic } from "../../domain/cluster/useLiveTopic";
import { EMPTY_EVENT_FEED, eventFeedReducer, isFinalState, listQuery, mergeEvents, newerSummary, type ListViewState } from "./campaignModel";
import { planOfConfig, startBlocker } from "./resourcePlan";

/** Queries and live feeds of the Campaigns section. */

export const LIST_POLL_MS = 4_000;
export const DETAIL_POLL_MS = 4_000;
const EVENTS_PAGE = 200;
const EVENTS_PAGES_MAX = 50;

const retryUnlessUnreachable = (failureCount: number, error: unknown) => !(error instanceof OperatorApiError && (error.unreachable || (error.status !== null && error.status < 500))) && failureCount < 2;

/** The operator client of the selected cluster, or null without one. */
export function useOperatorClient(): OperatorClient | null {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  return useMemo(() => (operatorUrl ? createOperatorClient(operatorUrl) : null), [operatorUrl]);
}

// List

export function useCampaignList(view: ListViewState) {
  const client = useOperatorClient();
  const query = listQuery(view);
  return useQuery({
    queryKey: ["campaigns", client?.baseUrl, "list", query],
    queryFn: ({ signal }) => (client as OperatorClient).listCampaigns(query, signal),
    enabled: client !== null,
    refetchInterval: LIST_POLL_MS,
    placeholderData: keepPreviousData,
    retry: retryUnlessUnreachable,
  });
}

/** The detail (totals) of each campaign in a list, kept fresh while the campaign is not finished. */
export function useCampaignDetails(campaigns: readonly CampaignSummary[]) {
  const client = useOperatorClient();
  const results = useQueries({
    queries: campaigns.map((campaign) => ({
      queryKey: ["campaigns", client?.baseUrl, "detail", campaign.campaign_id],
      queryFn: ({ signal }: { signal: AbortSignal }) => (client as OperatorClient).getCampaign(campaign.campaign_id, signal),
      enabled: client !== null,
      refetchInterval: isFinalState(campaign.actual_state) ? false : LIST_POLL_MS + 1_000,
      staleTime: isFinalState(campaign.actual_state) ? 60_000 : 2_000,
      retry: retryUnlessUnreachable,
    })),
  });
  return useMemo(() => {
    const byId = new Map<string, CampaignDetail>();
    results.forEach((result, index) => {
      if (result.data) {
        byId.set(campaigns[index].campaign_id, result.data);
      }
    });
    return byId;
  }, [results, campaigns]);
}

// Detail

export interface CampaignFeed {
  detail: CampaignDetail | null;
  /** Where the numbers come from: the live channel, or polling while the channel is down. */
  source: "live" | "poll";
  liveStatus: ReturnType<typeof useLiveTopic>["status"];
  error: OperatorApiError | Error | null;
  loading: boolean;
  lastEventId: number | null;
  pushedEvents: CampaignTopicState["events"];
  /** Applies the answer of a control right away (the live update follows with the engine's next transaction). */
  applySummary: (summary: CampaignSummary) => void;
  refetch: () => void;
}

export function useCampaignFeed(campaignId: string): CampaignFeed {
  const client = useOperatorClient();
  const live = useLiveTopic(campaignTopic(campaignId), campaignReducer);
  const isLive = live.status === "live";
  const queryClient = useQueryClient();
  const queryKey = useMemo(() => ["campaigns", client?.baseUrl, "detail", campaignId], [client, campaignId]);
  const rest = useQuery({
    queryKey,
    queryFn: ({ signal }) => (client as OperatorClient).getCampaign(campaignId, signal),
    enabled: client !== null,
    refetchInterval: isLive ? false : DETAIL_POLL_MS,
    retry: retryUnlessUnreachable,
  });
  const [override, setOverride] = useState<CampaignSummary | null>(null);
  const applySummary = useCallback(
    (summary: CampaignSummary) => {
      setOverride(summary);
      queryClient.setQueryData<CampaignDetail>(queryKey, (current) => (current ? { ...current, ...summary } : current));
      void queryClient.invalidateQueries({ queryKey: ["campaigns", client?.baseUrl, "list"] });
    },
    [queryClient, queryKey, client]
  );
  const liveDetail = live.data?.detail ?? null;
  const base = isLive && liveDetail ? liveDetail : (rest.data ?? liveDetail);
  const detail = useMemo(() => {
    if (!base) {
      return null;
    }
    if (!override || override.campaign_id !== base.campaign_id) {
      return base;
    }
    const newer = newerSummary(base, override);
    return newer === base ? base : { ...base, ...override };
  }, [base, override]);
  const error = !detail && rest.error ? (rest.error as Error) : live.status === "error" && !detail ? new Error(live.error ?? "the live channel refused the campaign") : null;
  return {
    detail,
    source: isLive ? "live" : "poll",
    liveStatus: live.status,
    error,
    loading: !detail && !error,
    lastEventId: live.data?.lastEventId ?? null,
    pushedEvents: live.data?.events ?? [],
    applySummary,
    refetch: () => void rest.refetch(),
  };
}

/** The campaign's events, oldest first: the history from the events route, then the ones the live channel pushes (or polling). */
export function useCampaignEvents(campaignId: string, lastEventId: number | null, pushed: CampaignTopicState["events"], polling: boolean) {
  const client = useOperatorClient();
  const [feed, dispatch] = useReducer(eventFeedReducer, EMPTY_EVENT_FEED);
  const lastIdRef = useRef(0);
  const loading = useRef(false);

  useEffect(() => {
    lastIdRef.current = feed.lastId;
  }, [feed.lastId]);

  useEffect(() => {
    dispatch({ type: "reset" });
    lastIdRef.current = 0;
  }, [campaignId, client]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!client || loading.current) {
        return;
      }
      loading.current = true;
      try {
        let after = lastIdRef.current;
        for (let page = 0; page < EVENTS_PAGES_MAX; page += 1) {
          const { items } = await client.listEvents(campaignId, { after, limit: EVENTS_PAGE }, signal);
          if (items.length === 0) {
            break;
          }
          dispatch({ type: "merge", events: items });
          after = items[items.length - 1].event_id;
          lastIdRef.current = after;
          if (items.length < EVENTS_PAGE) {
            break;
          }
        }
      } catch {
        // The next trigger tries again; the feed keeps what it has
      } finally {
        loading.current = false;
      }
    },
    [client, campaignId]
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, lastEventId]);

  useEffect(() => {
    if (!polling) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = setInterval(() => void load(controller.signal), DETAIL_POLL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [polling, load]);

  return useMemo(() => mergeEvents(feed.events, pushed), [feed.events, pushed]);
}

export function useCampaignConfig(campaignId: string) {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["campaigns", client?.baseUrl, "config", campaignId],
    queryFn: ({ signal }) => (client as OperatorClient).getCampaignConfig(campaignId, signal),
    enabled: client !== null,
    staleTime: 30_000,
    retry: retryUnlessUnreachable,
  });
}

/** Why the campaign of a stored config cannot start on the selected cluster's machines, or null; follows the nodes while mounted. */
export function useStartBlocker(config: CampaignConfig | undefined): string | null {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const nodesState = useNodesStore();
  const loaded = operatorUrl !== null && nodesState.operatorUrl === operatorUrl && nodesState.loaded;
  const current = config?.versions.find((version) => version.version === config.current_version)?.config;
  return useMemo(() => startBlocker(loaded && current ? planOfConfig(current, nodesState.nodes) : null), [loaded, current, nodesState.nodes]);
}

export function useCampaignControl(campaignId: string, onDone: (summary: CampaignSummary) => void) {
  const client = useOperatorClient();
  return useMutation({
    mutationFn: (control: CampaignControl) => (client as OperatorClient).controlCampaign(campaignId, control),
    onSuccess: onDone,
  });
}

// Catalog

export function useCatalogClasses() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "classes"],
    queryFn: ({ signal }) => listCatalogClasses(client as OperatorClient, {}, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}

export function useCatalogStacks() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "stacks"],
    queryFn: ({ signal }) => getCatalogStacks(client as OperatorClient, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}
