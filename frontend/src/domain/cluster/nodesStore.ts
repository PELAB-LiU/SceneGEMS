import { useEffect } from "react";
import { create } from "zustand";
import type { LiveChannel } from "./liveChannel";
import { getLiveChannel } from "./liveChannels";
import { NODES_TOPIC } from "./liveProtocol";
import { nodesReducer, upsertNode } from "./liveTopics";
import { LiveTopicWatcher } from "./liveTopicWatcher";
import { createOperatorClient, describeOperatorError, OperatorApiError, type OperatorClient } from "./operatorApi";
import type { NodeView } from "./schemas";

/**
 * The nodes of the selected cluster: fed by the live channel's `nodes` topic, and by a
 * REST poll of `GET /cluster/nodes` while the topic is not live (channel down, topic
 * refused, or a master without the live channel).
 */

export type NodesSource = "live" | "poll";

export interface NodesState {
  /** The operator URL the nodes belong to, or null when no feed runs. */
  operatorUrl: string | null;
  nodes: NodeView[];
  /** Whether any answer arrived for this cluster yet. */
  loaded: boolean;
  source: NodesSource | null;
  /** The last problem of the poll, cleared by the next answer. */
  error: string | null;
  /** True when the last poll could not reach the master at all. */
  unreachable: boolean;
  /** Wall time (ms) of the last change. */
  updatedAt: number | null;
  /** Puts a node view from another answer (drain, resume) into the list. */
  applyNode: (node: NodeView) => void;
}

const EMPTY = {
  nodes: [] as NodeView[],
  loaded: false,
  source: null,
  error: null,
  unreachable: false,
  updatedAt: null,
};

export const useNodesStore = create<NodesState>()((set) => ({
  operatorUrl: null,
  ...EMPTY,
  applyNode: (node) => set((state) => ({ nodes: upsertNode(state.nodes, node), updatedAt: Date.now() })),
}));

export interface NodesFeedOptions {
  channel?: LiveChannel;
  client?: OperatorClient;
  pollIntervalMs?: number;
  store?: typeof useNodesStore;
  now?: () => number;
}

export const NODES_POLL_INTERVAL_MS = 5_000;

/** Starts feeding the store with the nodes of one cluster; returns the function that stops it. */
export function startNodesFeed(operatorUrl: string, options: NodesFeedOptions = {}): () => void {
  const store = options.store ?? useNodesStore;
  const client = options.client ?? createOperatorClient(operatorUrl);
  const channel = options.channel ?? getLiveChannel(operatorUrl);
  const pollIntervalMs = options.pollIntervalMs ?? NODES_POLL_INTERVAL_MS;
  const now = options.now ?? Date.now;

  store.setState({ operatorUrl, ...EMPTY });

  let stopped = false;
  let live = false;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollAbort: AbortController | null = null;

  const poll = async () => {
    pollTimer = null;
    pollAbort = new AbortController();
    try {
      const { items } = await client.listNodes(pollAbort.signal);
      if (!stopped && !live) {
        store.setState({ nodes: [...items].sort((a, b) => a.name.localeCompare(b.name)), loaded: true, source: "poll", error: null, unreachable: false, updatedAt: now() });
      }
    } catch (error) {
      if (!stopped && !live) {
        store.setState({ error: describeOperatorError(error), unreachable: error instanceof OperatorApiError && error.unreachable });
      }
    } finally {
      pollAbort = null;
    }
    if (!stopped && !live) {
      pollTimer = setTimeout(() => void poll(), pollIntervalMs);
    }
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    pollAbort?.abort();
    pollAbort = null;
  };

  const watcher = new LiveTopicWatcher(channel, NODES_TOPIC, nodesReducer);
  const onTopic = () => {
    const state = watcher.getState();
    if (state.status === "live" && state.data !== null) {
      live = true;
      stopPolling();
      store.setState({ nodes: state.data, loaded: true, source: "live", error: null, unreachable: false, updatedAt: now() });
      return;
    }
    if (live) {
      live = false;
      if (pollTimer === null && pollAbort === null) {
        void poll();
      }
    }
  };
  const offTopic = watcher.subscribe(onTopic);
  if (!live) {
    void poll();
  }

  return () => {
    stopped = true;
    stopPolling();
    offTopic();
    if (store.getState().operatorUrl === operatorUrl) {
      store.setState({ operatorUrl: null, ...EMPTY });
    }
  };
}

const feeds = new Map<string, { count: number; stop: () => void }>();

/** Shares one feed per cluster between components; returns the release function. */
export function acquireNodesFeed(operatorUrl: string): () => void {
  let feed = feeds.get(operatorUrl);
  if (!feed) {
    feed = { count: 0, stop: startNodesFeed(operatorUrl) };
    feeds.set(operatorUrl, feed);
  }
  feed.count += 1;
  let released = false;
  return () => {
    if (released) {
      return;
    }
    released = true;
    const current = feeds.get(operatorUrl);
    if (!current) {
      return;
    }
    current.count -= 1;
    if (current.count === 0) {
      feeds.delete(operatorUrl);
      current.stop();
    }
  };
}

/** Keeps the nodes feed of a cluster running while the calling component is mounted. */
export function useNodesFeed(operatorUrl: string | null): void {
  useEffect(() => (operatorUrl ? acquireNodesFeed(operatorUrl) : undefined), [operatorUrl]);
}
