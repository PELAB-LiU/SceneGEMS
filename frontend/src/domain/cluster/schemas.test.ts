import { describe, expect, it } from "vitest";
import {
  sampleCampaignDetail,
  sampleCampaignSummary,
  sampleCase,
  sampleEvent,
  sampleJob,
  sampleLogLine,
  sampleMasterStatus,
  sampleNode,
  sampleRunRecord,
  sampleVerdict,
} from "../../test/fixtures/clusterViews";
import {
  campaignConfigSchema,
  campaignDetailSchema,
  campaignEventSchema,
  campaignSummarySchema,
  caseDetailSchema,
  jobDetailSchema,
  jobViewSchema,
  masterStatusSchema,
  nodeListSchema,
  nodeViewSchema,
  runRecordSchema,
  verdictSchema,
} from "./schemas";

describe("operator API schemas", () => {
  it("parses a node view with and without the machine", () => {
    const node = nodeViewSchema.parse(sampleNode());
    expect(node.machine).toBe("lab-gpu-1");
    expect(node.capabilities["simulation.kinematic"]).toEqual({ slots: 8, slots_in_use: 8 });

    const { machine: _machine, ...withoutMachine } = sampleNode();
    void _machine;
    expect(nodeViewSchema.parse(withoutMachine).machine).toBeUndefined();
    expect(nodeViewSchema.parse(sampleNode({ machine: null })).machine).toBeNull();
  });

  it("parses an out-of-date node with its mismatching images", () => {
    const node = nodeViewSchema.parse(
      sampleNode({
        out_of_date: true,
        fingerprint_mismatches: [
          { image: "scenegems-node", required: "sha256:aaaa", actual: "sha256:9999" },
          { image: "scenegems-monitoring", required: "sha256:bbbb", actual: null },
        ],
      })
    );
    expect(node.fingerprint_mismatches[1].actual).toBeNull();
  });

  it("refuses a node with an unknown status or a missing field", () => {
    expect(nodeViewSchema.safeParse(sampleNode({ status: "sleeping" })).success).toBe(false);
    const { leases: _leases, ...withoutLeases } = sampleNode();
    void _leases;
    expect(nodeViewSchema.safeParse(withoutLeases).success).toBe(false);
    expect(nodeListSchema.parse([sampleNode(), sampleNode({ node_id: "node-b", name: "worker-b" })])).toHaveLength(2);
  });

  it("parses the master status", () => {
    const status = masterStatusSchema.parse(sampleMasterStatus);
    expect(status.expected_fingerprints.images["scenegems-node"]).toBe("sha256:aaaa");
  });

  it("parses jobs with available_at, progress and log lines", () => {
    const job = jobViewSchema.parse(sampleJob());
    expect(job.available_at).toBe("2026-10-26T09:58:00+00:00");
    expect(job.progress?.progress).toBe(0.5);
    expect(jobViewSchema.parse(sampleJob({ progress: null, state: "queued", lease_owner: null })).progress).toBeNull();

    const detail = jobDetailSchema.parse({
      ...sampleJob(),
      payload: { request_id: "r1" },
      events: [
        { at: "2026-10-26T09:58:00+00:00", kind: "submitted", from_state: null, to_state: "queued", attempt: 0, lease_id: null, node_id: null, detail: {} },
      ],
      log_lines: [sampleLogLine],
    });
    expect(detail.log_lines[0].text).toBe("sample 12 valid");
  });

  it("parses campaign summary, detail, events and config", () => {
    expect(campaignSummarySchema.parse(sampleCampaignSummary).actual_state).toBe("running");
    const detail = campaignDetailSchema.parse(sampleCampaignDetail());
    expect(detail.classes[0].verdicts["0"]).toEqual({ passed: 2, failed: 1 });
    expect(detail.totals.verdicts.failed).toBe(1);
    expect(campaignEventSchema.parse(sampleEvent).kind).toBe("started");
    expect(
      campaignConfigSchema.parse({
        current_version: 1,
        versions: [{ version: 1, config_hash: "h", created_at: "2026-10-26T09:00:00+00:00", config: { name: "x" } }],
      }).versions
    ).toHaveLength(1);
    expect(campaignSummarySchema.safeParse({ ...sampleCampaignSummary, actual_state: "flying" }).success).toBe(false);
  });

  it("parses a case with its jobs, run records and verdicts, and the case index when present", () => {
    const detail = caseDetailSchema.parse({
      ...sampleCase,
      progress: { steps: {} },
      jobs: [
        {
          stage: "generate_scene",
          run_index: null,
          repeat_index: null,
          idempotency_key: "campaign:c1:case:5:generate_scene",
          job_id: "job-1",
          intent: false,
          created_at: "2026-10-26T09:10:00+00:00",
          submitted_at: "2026-10-26T09:10:01+00:00",
          job: {
            job_type: "scene_generation",
            state: "succeeded",
            priority: 100,
            attempt: 1,
            failed_attempts: 0,
            max_attempts: 3,
            lease_owner: null,
            available_at: "2026-10-26T09:10:01+00:00",
            started_at: "2026-10-26T09:10:02+00:00",
            finished_at: "2026-10-26T09:11:00+00:00",
            error: null,
          },
        },
        {
          stage: "simulate",
          run_index: 0,
          repeat_index: 0,
          idempotency_key: "campaign:c1:case:5:simulate:0:0",
          job_id: null,
          intent: true,
          created_at: "2026-10-26T09:12:00+00:00",
          submitted_at: null,
          job: null,
        },
      ],
      run_records: [sampleRunRecord],
      verdicts: [sampleVerdict],
    });
    expect(detail.jobs[1].job).toBeNull();
    expect(detail.run_records[0].artifacts.state_log).toBe("sha256:cccc");
    expect(detail.verdicts[0].failed_rules).toEqual(["rule_8"]);
    expect(verdictSchema.parse({ ...sampleVerdict, case_index: 2 }).case_index).toBe(2);
    expect(runRecordSchema.parse(sampleRunRecord).case_index).toBeUndefined();
  });
});
