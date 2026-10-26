import { describe, expect, it, vi } from "vitest";
import { sampleCampaignDetail } from "../../test/fixtures/clusterViews";
import { sampleCatalogClasses, sampleCatalogStacks, sampleValidationResult } from "../../test/fixtures/campaignCatalog";
import {
  catalogClassSchema,
  catalogStacksSchema,
  createCampaign,
  getCatalogStacks,
  listCatalogClasses,
  validateCampaignConfig,
  validationResultSchema,
} from "./campaignApi";
import { createOperatorClient, OperatorApiError } from "./operatorApi";

const BASE = "http://127.0.0.1:5174";

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

function clientWith(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>) {
  const spy = vi.fn(fetchImpl);
  return { client: createOperatorClient(BASE, { fetch: spy as unknown as typeof fetch }), spy };
}

describe("catalog schemas", () => {
  it("parses the sample class catalog", () => {
    for (const entry of sampleCatalogClasses) {
      expect(catalogClassSchema.parse(entry).class_id).toBe(entry.class_id);
    }
  });

  it("parses the stacks catalog with its groups, monitors and generators", () => {
    const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
    expect(parsed.stacks.map((stack) => stack.id)).toEqual(["kinematic.replay", "kinematic.usv_navigation"]);
    expect(parsed.stacks[1].groups[0].parameters.map((parameter) => parameter.key)).toContain("goal");
    expect(parsed.stacks[0].environment.wind).toBe("unsupported");
    expect(parsed.trajectory_generators.find((generator) => generator.id === "straight")?.params_field).toBeNull();
    expect(parsed.monitors.find((monitor) => monitor.id === "live")?.supports_early_stop).toBe(true);
    expect(parsed.unavailable_stacks[0].reasons[0]).toMatch(/Gazebo/);
  });

  it("rejects a parameter type it does not know", () => {
    const broken = structuredClone(sampleCatalogStacks) as typeof sampleCatalogStacks;
    (broken.stacks[0].parameters[0] as { type: string }).type = "matrix";
    expect(catalogStacksSchema.safeParse(broken).success).toBe(false);
  });

  it("accepts parameters without the optional bounds (the server leaves them out)", () => {
    const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
    const timeStep = parsed.trajectory_generators[0].parameters[0];
    expect(timeStep.maximum).toBeUndefined();
    expect(timeStep.minimum).toBe(1);
  });
});

describe("validation result schema", () => {
  it("parses the sample answer", () => {
    const parsed = validationResultSchema.parse(sampleValidationResult);
    expect(parsed.cases_planned).toBe(30);
    expect(parsed.classes).toHaveLength(2);
    expect(parsed.runs[0].repeatability_tier).toBe("exact");
  });

  it("requires valid to be true", () => {
    expect(validationResultSchema.safeParse({ ...sampleValidationResult, valid: false }).success).toBe(false);
  });

  it("allows an unnamed run and a run without a tier", () => {
    const parsed = validationResultSchema.parse({ ...sampleValidationResult, runs: [{ run_index: 0, name: null, repeatability_tier: null, warnings: ["w"] }] });
    expect(parsed.runs[0].warnings).toEqual(["w"]);
  });
});

describe("catalog calls", () => {
  it("reads the classes with their total and joins pages", async () => {
    const page = (offset: number) => sampleCatalogClasses.slice(offset, offset + 4);
    const { client, spy } = clientWith(async (url) => {
      const offset = Number(new URL(url).searchParams.get("offset"));
      return jsonResponse(page(offset), { headers: { "X-Total-Count": String(sampleCatalogClasses.length) } });
    });
    const result = await listCatalogClasses(client, { folder: "2vessel_0obstacle_scenarios" });
    expect(result.total).toBe(sampleCatalogClasses.length);
    expect(result.items).toHaveLength(sampleCatalogClasses.length);
    expect(spy.mock.calls).toHaveLength(2);
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/catalog/classes?folder=2vessel_0obstacle_scenarios&limit=1000&offset=0`);
    expect(spy.mock.calls[1][0]).toContain("offset=4");
  });

  it("stops on an empty page even when the total is larger", async () => {
    const { client, spy } = clientWith(async () => jsonResponse([], { headers: { "X-Total-Count": "50" } }));
    expect((await listCatalogClasses(client)).items).toEqual([]);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("reads the stacks", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleCatalogStacks));
    const stacks = await getCatalogStacks(client);
    expect(stacks.resolver.available).toBe(5);
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/catalog/stacks`);
  });
});

describe("validate and create", () => {
  it("posts the YAML as the config of a JSON body", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleValidationResult));
    const result = await validateCampaignConfig(client, "name: x\n");
    expect(result.config_hash).toBe("9f2c1d");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/cluster/campaigns/validate`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ config: "name: x\n" });
  });

  it("surfaces the reasons of a refused config", async () => {
    const detail = { message: "the campaign config is not valid", reasons: ["scope.0: no class 'x' in the catalog", "execution.runs.0 (a): stack unavailable"] };
    const { client } = clientWith(async () => jsonResponse({ detail }, { status: 422 }));
    const error = await validateCampaignConfig(client, "x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OperatorApiError);
    expect((error as OperatorApiError).status).toBe(422);
    expect((error as OperatorApiError).reasons).toEqual(detail.reasons);
  });

  it("creates paused unless asked to start, and parses the new campaign", async () => {
    const { client, spy } = clientWith(async () => jsonResponse({ ...sampleCampaignDetail(), desired_state: "paused", actual_state: "created" }, { status: 201 }));
    const created = await createCampaign(client, "name: x\n");
    expect(created.actual_state).toBe("created");
    expect(JSON.parse(spy.mock.calls[0][1]?.body as string)).toEqual({ config: "name: x\n", start: false });
    await createCampaign(client, "name: x\n", { start: true, name: "other" });
    expect(JSON.parse(spy.mock.calls[1][1]?.body as string)).toEqual({ config: "name: x\n", start: true, name: "other" });
    expect(spy.mock.calls[1][0]).toBe(`${BASE}/cluster/campaigns`);
  });
});
