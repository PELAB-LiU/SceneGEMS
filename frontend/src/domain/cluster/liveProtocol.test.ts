import { describe, expect, it } from "vitest";
import {
  campaignTopic,
  instanceTopic,
  jobInstanceName,
  jobTopic,
  NODES_TOPIC,
  parseServerMessage,
  parseTopic,
  pingMessage,
  subscribeMessage,
  unsubscribeMessage,
} from "./liveProtocol";

describe("live channel protocol", () => {
  it("names and parses topics", () => {
    expect(parseTopic(NODES_TOPIC)).toEqual({ kind: "nodes" });
    expect(parseTopic(campaignTopic("c1"))).toEqual({ kind: "campaign", campaignId: "c1" });
    expect(parseTopic(jobTopic("j:1"))).toEqual({ kind: "job", jobId: "j:1" });
    const instance = instanceTopic("node-a", jobInstanceName("job-9", 2));
    expect(instance).toBe("instance:node-a/job-job-9-2");
    expect(parseTopic(instance)).toEqual({ kind: "instance", nodeId: "node-a", instance: "job-job-9-2" });
    expect(parseTopic("instance:node-a")).toBeNull();
    expect(parseTopic("campaign:")).toBeNull();
    expect(parseTopic("weather:today")).toBeNull();
  });

  it("builds client messages with the version", () => {
    expect(subscribeMessage("nodes")).toEqual({ type: "subscribe", version: 1, topic: "nodes" });
    expect(unsubscribeMessage("nodes")).toEqual({ type: "unsubscribe", version: 1, topic: "nodes" });
    expect(pingMessage()).toEqual({ type: "ping", version: 1 });
  });

  it("parses every server message", () => {
    const frames = [
      { type: "subscribed", version: 1, topic: "nodes", snapshot: [] },
      { type: "update", version: 1, topic: "nodes", seq: 1, data: { removed: "n" } },
      { type: "unsubscribed", version: 1, topic: "nodes" },
      { type: "error", version: 1, message: "unknown topic", topic: "job:x" },
      { type: "error", version: 1, message: "bad frame" },
      { type: "pong", version: 1 },
    ];
    for (const frame of frames) {
      const parsed = parseServerMessage(JSON.stringify(frame));
      expect(parsed.ok).toBe(true);
    }
  });

  it("refuses frames of another version, unknown types and bad seq", () => {
    expect(parseServerMessage(JSON.stringify({ type: "pong", version: 2 })).ok).toBe(false);
    expect(parseServerMessage(JSON.stringify({ type: "hello", version: 1 })).ok).toBe(false);
    expect(parseServerMessage(JSON.stringify({ type: "update", version: 1, topic: "nodes", seq: 0, data: {} })).ok).toBe(false);
    expect(parseServerMessage("not json").ok).toBe(false);
  });
});
