/** The domain configuration files of the backend, read as the text the editor receives. */
const files = import.meta.glob<string>("../../../../../../backend/assets/domain_config/**/*.yaml", {
  query: "?raw",
  import: "default",
  eager: true,
});

function fileText(name: string): string {
  const entry = Object.entries(files).find(([path]) => path.endsWith(name));
  if (!entry) {
    throw new Error(`Domain file ${name} not found`);
  }
  return entry[1];
}

export const GENERAL_COLREGS = fileText("colregs_constants/general_maritime_constants.yaml");
export const WARA_PS_COLREGS = fileText("colregs_constants/wara_ps_constants.yaml");
export const VESSEL_TYPES = fileText("vessel_types/vessel_types.yaml");
export const OBSTACLE_TYPES = fileText("static_obstacle_types/static_obstacle_types.yaml");
export const VESSEL_DYNAMICS = fileText("vessel_dynamics/vessel_dynamics.yaml");

export const ALL_DOMAIN_FILES: Record<string, string> = {
  "general_maritime_constants.yaml": GENERAL_COLREGS,
  "wara_ps_constants.yaml": WARA_PS_COLREGS,
  "vessel_types.yaml": VESSEL_TYPES,
  "static_obstacle_types.yaml": OBSTACLE_TYPES,
  "vessel_dynamics.yaml": VESSEL_DYNAMICS,
};
