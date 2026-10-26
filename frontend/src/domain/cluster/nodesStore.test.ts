import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleNode } from "../../test/fixtures/clusterViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { LiveChannel } from "./liveChannel";
import { acquireNodesFeed, startNodesFeed, useNodesStore } from "./nodesStore";
import { resetLiveChannels } from "./liveChannels";
import { nodeViewSchema, type NodeView } from "./schemas";
import { OperatorApiError, type OperatorClient } from "./operatorApi";

const URL = "http://127.0.0.1:5174";

function node(overrides: Record<string, unknown> = {}): NodeView {
  return nodeViewSchema.parse(sampleNode(overrides));
}

function fakeClient(listNodes: () => Promise<{ items: NodeView[]; total: number | null }>) {
  const spy = vi.fn(listNodes);
  return { client: { listNodes: spy } as unknown as OperatorClient, spy };
}

function makeChannel() {
  return new LiveChannel("ws://127.0.0.1:5174/cluster/live", { createSocket: MockWebSocket.factory, reconnectBaseMs: 100, random: () => 0.5 });
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("nodes feed", () => {
  it("polls while the live channel is down, then follows the nodes topic", async () => {
    const { client, spy } = fakeClient(async () => ({ items: [node({ node_id: "b", name: "worker-b" }), node()], total: null }));
    const stop = startNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(useNodesStore.getState()).toMatchObject({ operatorUrl: URL, loaded: true, source: "poll", error: null });
    expect(useNodesStore.getState().nodes.map((entry) => entry.name)).toEqual(["worker-a", "worker-b"]);

    await vi.advanceTimersByTimeAsync(1000);
    expect(spy).toHaveBeenCalledTimes(2);

    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "nodes", snapshot: [sampleNode({ status: "draining" })] });
    expect(useNodesStore.getState().source).toBe("live");
    expect(useNodesStore.getState().nodes[0].status).toBe("draining");

    await vi.advanceTimersByTimeAsync(5000);
    expect(spy).toHaveBeenCalledTimes(2);

    socket.receive({ type: "update", topic: "nodes", seq: 1, data: { removed: "node-a1" } });
    expect(useNodesStore.getState().nodes).toEqual([]);

    socket.drop();
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(3);
    expect(useNodesStore.getState().source).toBe("poll");

    stop();
    expect(useNodesStore.getState().operatorUrl).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("marks an unreachable master and keeps polling", async () => {
    const { client, spy } = fakeClient(async () => {
      throw new OperatorApiError("network", "cannot reach http://127.0.0.1:5174 (Failed to fetch)", "/cluster/nodes");
    });
    const stop = startNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(useNodesStore.getState()).toMatchObject({ loaded: false, unreachable: true });
    expect(useNodesStore.getState().error).toContain("cannot reach");
    await vi.advanceTimersByTimeAsync(1000);
    expect(spy).toHaveBeenCalledTimes(2);
    stop();
  });

  it("applies a node from a drain or resume answer", async () => {
    const { client } = fakeClient(async () => ({ items: [node()], total: null }));
    const stop = startNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    useNodesStore.getState().applyNode(node({ status: "draining" }));
    expect(useNodesStore.getState().nodes).toHaveLength(1);
    expect(useNodesStore.getState().nodes[0].status).toBe("draining");
    stop();
  });

  it("shares one feed per cluster between components", async () => {
    resetLiveChannels({ createSocket: MockWebSocket.factory });
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify([sampleNode()]), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const releaseA = acquireNodesFeed(URL);
    const releaseB = acquireNodesFeed(URL);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(1);

    releaseA();
    releaseA();
    expect(useNodesStore.getState().operatorUrl).toBe(URL);
    releaseB();
    expect(useNodesStore.getState().operatorUrl).toBeNull();
    resetLiveChannels();
  });
});
