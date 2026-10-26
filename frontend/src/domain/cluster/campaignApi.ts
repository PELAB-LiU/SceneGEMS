import { z } from "zod";
import type { OperatorClient } from "./operatorApi";
import { campaignDetailSchema } from "./schemas";

/**
 * The campaign routes the wizard needs besides the ones in `operatorApi.ts`: the class and stack
 * catalogs (`catalog_views.py`), validating a config and creating a campaign (`campaign_routes.py`).
 * Every answer is checked against a schema; a refused config arrives as an `OperatorApiError`
 * with status 422 and the server's reasons.
 */

// Catalog: classes

export const catalogClassSchema = z.object({
  class_id: z.string(),
  folder: z.string(),
  vessel_count: z.number().int(),
  obstacle_count: z.number().int(),
  content_hash: z.string(),
});

export type CatalogClass = z.infer<typeof catalogClassSchema>;

// Catalog: stacks, monitors, trajectory generators

export const PARAMETER_TYPES = ["number", "integer", "boolean", "string", "number_pair", "number_triple", "number_map", "object"] as const;
export const parameterTypeSchema = z.enum(PARAMETER_TYPES);

/** One configurable value (`catalog_views.parameter`). A `default` of null means it is left out and the system derives it. */
export const catalogParameterSchema = z.object({
  key: z.string(),
  type: parameterTypeSchema,
  default: z.unknown().nullable(),
  required: z.boolean(),
  description: z.string(),
  unit: z.string().nullish(),
  minimum: z.number().nullish(),
  exclusive_minimum: z.number().nullish(),
  maximum: z.number().nullish(),
  choices: z.array(z.string()).nullish(),
});

const stackTripleSchema = z.object({
  asv_software: z.string(),
  control_layer: z.string(),
  simulation_layer: z.string(),
});

export const catalogStackSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string(),
  simulation_layer: z.string(),
  mode: z.string(),
  available: z.boolean(),
  reasons: z.array(z.string()),
  repeatability_tier: z.string().nullable(),
  vessels: z.record(z.string(), stackTripleSchema),
  /** wind and waves: `supported`, `unmeasured` or `unsupported`. */
  environment: z.object({
    wind: z.string(),
    waves: z.string(),
    interactive_only: z.boolean(),
  }),
  parameters: z.array(catalogParameterSchema),
  groups: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      optional: z.boolean(),
      derived_when_absent: z.string().nullish(),
      parameters: z.array(catalogParameterSchema),
    })
  ),
});

export const unavailableStackSchema = z.object({
  asv_software: z.string(),
  control_layer: z.string(),
  simulation_layer: z.string(),
  status: z.string(),
  design_status: z.string(),
  available_in_resolver: z.boolean(),
  tier: z.string().nullable(),
  reasons: z.array(z.string()),
});

export const catalogMonitorSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string(),
  job_types: z.array(z.string()),
  supports_early_stop: z.boolean(),
});

export const catalogGeneratorSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string(),
  /** Where the generator's parameters go in the config (`params`), or null when they are fields of `trajectories`. */
  params_field: z.string().nullable(),
  parameters: z.array(catalogParameterSchema),
  /** Parameters every generator takes (`timeout_s`). */
  common_parameters: z.array(catalogParameterSchema),
});

export const catalogStacksSchema = z.object({
  stacks: z.array(catalogStackSchema),
  unavailable_stacks: z.array(unavailableStackSchema),
  monitors: z.array(catalogMonitorSchema),
  trajectory_generators: z.array(catalogGeneratorSchema),
  run_parameters: z.array(catalogParameterSchema),
  note: z.string(),
  resolver: z.object({ combinations: z.number().int(), available: z.number().int() }),
});

export type ParameterType = z.infer<typeof parameterTypeSchema>;
export type CatalogParameter = z.infer<typeof catalogParameterSchema>;
export type CatalogStack = z.infer<typeof catalogStackSchema>;
export type UnavailableStack = z.infer<typeof unavailableStackSchema>;
export type CatalogMonitor = z.infer<typeof catalogMonitorSchema>;
export type CatalogGenerator = z.infer<typeof catalogGeneratorSchema>;
export type CatalogStacks = z.infer<typeof catalogStacksSchema>;

// Validating a config

export const validatedClassSchema = z.object({
  class_id: z.string(),
  content_hash: z.string(),
  vessel_count: z.number().int(),
  obstacle_count: z.number().int(),
  quota: z.number().int(),
  failure_budget: z.number().int(),
});

export const validationResultSchema = z.object({
  valid: z.literal(true),
  name: z.string(),
  config_hash: z.string(),
  classes: z.array(validatedClassSchema),
  /** The sum of the quotas: the complete cases the campaign aims for. */
  cases_planned: z.number().int(),
  runs: z.array(
    z.object({
      run_index: z.number().int(),
      name: z.string().nullable(),
      repeatability_tier: z.string().nullable(),
      warnings: z.array(z.string()),
    })
  ),
});

export type ValidatedClass = z.infer<typeof validatedClassSchema>;
export type ValidationResult = z.infer<typeof validationResultSchema>;

const CAMPAIGNS_PATH = "/cluster/campaigns";
const CATALOG_PATH = "/cluster/catalog";

/** The largest page the catalog route serves. */
export const CATALOG_PAGE_LIMIT = 1000;

export interface CatalogClassPage {
  items: CatalogClass[];
  /** Classes the filters match, including those beyond the page. */
  total: number;
}

/** Every class of the catalog that matches the filters, in catalog order (pages of 1000 are joined). */
export async function listCatalogClasses(
  client: OperatorClient,
  filters: { folder?: string; pattern?: string } = {},
  signal?: AbortSignal
): Promise<CatalogClassPage> {
  const items: CatalogClass[] = [];
  let total = 0;
  for (;;) {
    const { data, total: reported } = await client.request("GET", `${CATALOG_PATH}/classes`, z.array(catalogClassSchema), {
      query: { ...filters, limit: CATALOG_PAGE_LIMIT, offset: items.length },
      signal,
    });
    items.push(...data);
    total = reported ?? items.length;
    if (data.length === 0 || items.length >= total) {
      break;
    }
  }
  return { items, total };
}

export async function getCatalogStacks(client: OperatorClient, signal?: AbortSignal): Promise<CatalogStacks> {
  return (await client.request("GET", `${CATALOG_PATH}/stacks`, catalogStacksSchema, { signal })).data;
}

/** Checks a config (YAML text) against the catalog and the vessel stack resolver; nothing is stored. Rejects with the reasons on 422. */
export async function validateCampaignConfig(client: OperatorClient, yamlText: string, signal?: AbortSignal): Promise<ValidationResult> {
  return (await client.request("POST", `${CAMPAIGNS_PATH}/validate`, validationResultSchema, { body: { config: yamlText }, signal })).data;
}

/** Creates the campaign from a config (YAML text): paused, or running at once with `start`. */
export async function createCampaign(client: OperatorClient, yamlText: string, options: { name?: string; start?: boolean } = {}) {
  const body: { config: string; name?: string; start: boolean } = { config: yamlText, start: options.start === true };
  if (options.name !== undefined) {
    body.name = options.name;
  }
  return (await client.request("POST", CAMPAIGNS_PATH, campaignDetailSchema, { body })).data;
}
