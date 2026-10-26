import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleNode } from "../../test/fixtures/clusterViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { LiveChannel } from "./liveChannel";
import { nodesReducer } from "./liveTopics";
import { LiveTopicWatcher } from "./liveTopicWatcher";

function makeChannel() {
  return new LiveChannel("ws://m/cluster/live", { createSocket: MockWebSocket.factory, reconnectBaseMs: 100, random: () => 0.5 });
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LiveTopicWatcher", () => {
  it("goes from waiting to live, offline on a lost connection and live again with the new snapshot", () => {
    const channel = makeChannel();
    const watcher = new LiveTopicWatcher(channel, "nodes", nodesReducer);
    expect(watcher.getState().status).toBe("idle");
    const changes = vi.fn();
    const off = watcher.subscribe(changes);
    expect(watcher.getState().status).toBe("waiting");

    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "nodes", snapshot: [sampleNode()] });
    expect(watcher.getState()).toMatchObject({ status: "live", seq: 0, error: null });
    expect(watcher.getState().data?.[0].name).toBe("worker-a");

    socket.receive({ type: "update", topic: "nodes", seq: 1, data: { node: sampleNode({ status: "draining" }) } });
    expect(watcher.getState().seq).toBe(1);
    expect(watcher.getState().data?.[0].status).toBe("draining");

    socket.drop();
    expect(watcher.getState().status).toBe("offline");
    expect(watcher.getState().data?.[0].status).toBe("draining");

    vi.advanceTimersByTime(100);
    const next = MockWebSocket.latest();
    next.open();
    expect(watcher.getState().status).toBe("waiting");
    next.receive({ type: "subscribed", topic: "nodes", snapshot: [] });
    expect(watcher.getState()).toMatchObject({ status: "live", data: [] });
    expect(changes).toHaveBeenCalled();

    off();
    expect(watcher.getState().status).toBe("idle");
    expect(channel.subscriberCount("nodes")).toBe(0);
  });

  it("reports a snapshot that does not match and a refused topic", () => {
    const channel = makeChannel();
    const watcher = new LiveTopicWatcher(channel, "nodes", nodesReducer);
    watcher.subscribe(() => {});
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "nodes", snapshot: { not: "a list" } });
    expect(watcher.getState().status).toBe("error");
    expect(watcher.getState().error).toContain("unexpected snapshot of nodes");

    socket.receive({ type: "error", topic: "nodes", message: "unknown topic nodes" });
    expect(watcher.getState()).toMatchObject({ status: "error", error: "unknown topic nodes" });
  });

  it("keeps the state when an update does not match", () => {
    const channel = makeChannel();
    const watcher = new LiveTopicWatcher(channel, "nodes", nodesReducer);
    watcher.subscribe(() => {});
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "nodes", snapshot: [sampleNode()] });
    socket.receive({ type: "update", topic: "nodes", seq: 1, data: { what: 1 } });
    expect(watcher.getState().status).toBe("live");
    expect(watcher.getState().data).toHaveLength(1);
    expect(watcher.getState().error).toContain("unexpected update");
  });
});
