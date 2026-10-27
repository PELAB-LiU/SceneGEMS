import type { ArchitectureNode } from "../../domain/cluster/architectureApi";
import { cardFacts, chipsPerRow, measuredCount } from "./capabilitiesModel";

export const CONCRETE_WIDTH = 280;
export const META_WIDTH = 300;

const CHIP_ROW_HEIGHT = 30;
const DESCRIPTION_HEIGHT = 40;
const META_DESCRIPTION_HEIGHT = 60;

export function concreteHeight(node: ArchitectureNode): number {
  const shown = cardFacts(node);
  const chips = shown.length;
  const chipRows = Math.ceil(chips / chipsPerRow(shown));
  const hasMeta = node.tags.length > 0 || node.status === "planned" || measuredCount(node) > 0;
  // A card with value chips leaves its description to the detail panel; one without shows it
  return 16 + 28 + 8 + (chips === 0 ? DESCRIPTION_HEIGHT : 0) + (hasMeta ? 32 : 0) + (chips > 0 ? chipRows * CHIP_ROW_HEIGHT + 8 : 0) + 16;
}

export function metaHeight(): number {
  return 16 + 28 + 8 + META_DESCRIPTION_HEIGHT + 8 + 28 + 16;
}
