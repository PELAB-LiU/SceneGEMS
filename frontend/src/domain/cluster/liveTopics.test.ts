import { describe, expect, it } from "vitest";
import { sampleCampaignDetail, sampleClass, sampleCampaignSummary, sampleEvent, sampleJob, sampleLogLine, sampleNode } from "../../test/fixtures/clusterViews";
import {
  campaignReducer,
  instanceReducer,
  JOB_LOG_LINES_KEPT,
  jobReducer,
  nodesReducer,
  rawTopicReducer,
} from "./liveTopics";

describe("live topic reducers", () => {
  it("nodes: snapshot sorted by name, changed nodes replaced or added, removed nodes dropped", () => {
    let nodes = nodesReducer.snapshot([sampleNode({ node_id: "b", name: "worker-b" }), sampleNode({ node_id: "a", name: "worker-a" })]);
    expect(nodes.map((node) => node.node_id)).toEqual(["a", "b"]);
    nodes = nodesReducer.update(nodes, { node: sampleNode({ node_id: "b", name: "worker-b", status: "draining" }) }, 1);
    expect(nodes.find((node) => node.node_id === "b")?.status).toBe("draining");
    nodes = nodesReducer.update(nodes, { node: sampleNode({ node_id: "c", name: "aaa" }) }, 2);
    expect(nodes.map((node) => node.node_id)).toEqual(["c", "a", "b"]);
    nodes = nodesReducer.update(nodes, { removed: "a" }, 3);
    expect(nodes.map((node) => node.node_id)).toEqual(["c", "b"]);
    expect(() => nodesReducer.update(nodes, { node: { node_id: "x" } }, 4)).toThrow();
  });

  it("campaign: events appended once, summary merged, classes replaced with totals recomputed", () => {
    let state = campaignReducer.snapshot(sampleCampaignDetail());
    state = campaignReducer.update(state, { event: sampleEvent }, 1);
    state = campaignReducer.update(state, { event: sampleEvent }, 2);
    expect(state.events).toHaveLength(1);

    state = campaignReducer.update(state, { campaign: { ...sampleCampaignSummary, actual_state: "paused", desired_state: "paused" } }, 3);
    expect(state.detail.actual_state).toBe("paused");
    expect(state.detail.classes).toHaveLength(1);

    state = campaignReducer.update(
      state,
      {
        classes: [
          sampleClass({ complete: 10, in_flight: 0, state: "complete", verdicts: { "0": { passed: 9, failed: 1 } } }),
          sampleClass({ class_id: "class-b", quota: 5, complete: 0, dropped: 0, in_flight: 1, verdicts: {} }),
        ],
      },
      4
    );
    expect(state.detail.classes.map((entry) => entry.class_id)).toEqual(["class-a", "class-b"]);
    expect(state.detail.totals).toEqual({
      classes: 2,
      classes_open: 1,
      classes_complete: 1,
      classes_abandoned: 0,
      quota: 15,
      complete: 10,
      dropped: 1,
      in_flight: 1,
      verdicts: { passed: 9, failed: 1 },
    });
  });

  it("job: status from the snapshot's progress, then status, log and job updates", () => {
    let state = jobReducer.snapshot({ ...sampleJob(), logs: [sampleLogLine] });
    expect(state.status).toEqual({ progress: 0.5, message: "sampling", at: "2026-10-26T09:59:00+00:00" });
    expect(state.logs).toHaveLength(1);

    state = jobReducer.update(state, { status: { progress: 0.75, message: "almost", at: "2026-10-26T09:59:30+00:00" } }, 1);
    expect(state.status?.progress).toBe(0.75);

    const many = Array.from({ length: JOB_LOG_LINES_KEPT + 5 }, (_, index) => ({ ...sampleLogLine, text: `line ${index}` }));
    state = jobReducer.update(state, { logs: many }, 2);
    expect(state.logs).toHaveLength(JOB_LOG_LINES_KEPT);
    expect(state.logs.at(-1)?.text).toBe(`line ${JOB_LOG_LINES_KEPT + 4}`);

    state = jobReducer.update(state, { job: sampleJob({ state: "succeeded", finished_at: "2026-10-26T10:00:00+00:00" }) }, 3);
    expect(state.job.state).toBe("succeeded");
    expect(state.logs).toHaveLength(JOB_LOG_LINES_KEPT);

    expect(jobReducer.snapshot(sampleJob({ progress: null })).logs).toEqual([]);
  });

  it("instance: previews, frames and status", () => {
    let state = instanceReducer.snapshot({ node_id: "n", instance: "job-j-1", kind: "simulation", state: "running" });
    state = instanceReducer.update(state, { kind: "simulation_frames", job_id: "j", frames: [{ t: 0 }, { t: 1 }] }, 1);
    state = instanceReducer.update(state, { kind: "simulation_frames", job_id: "j", frames: [{ t: 2 }] }, 2);
    expect(state.frames).toEqual([{ t: 0 }, { t: 1 }, { t: 2 }]);
    expect(state.frameCount).toBe(3);

    state = instanceReducer.update(state, { kind: "scene_sample", request_id: "r", valid: true, evaluation_data: { a: 1 } }, 3);
    expect(state.sceneSample?.valid).toBe(true);
    state = instanceReducer.update(state, { kind: "trajectory_preview", request_id: "r", trajectories: [] }, 4);
    expect(state.trajectoryPreview?.request_id).toBe("r");
    state = instanceReducer.update(state, { kind: "status", state: "finished", message: "done" }, 5);
    expect([state.state, state.message]).toEqual(["finished", "done"]);
    expect(() => instanceReducer.update(state, { kind: "weather" }, 6)).toThrow();
  });

  it("raw: keeps the snapshot and the latest updates", () => {
    let state = rawTopicReducer.snapshot({ a: 1 });
    state = rawTopicReducer.update(state, "x", 1);
    expect(state).toEqual({ snapshot: { a: 1 }, updates: [{ seq: 1, data: "x" }] });
  });
});
