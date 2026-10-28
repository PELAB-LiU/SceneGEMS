import { createElement, type ReactNode } from "react";
import { RelationLabel } from "./actorNameFormat";

export function renderRelationId(relationId: string): ReactNode {
  return createElement(RelationLabel, { relationId });
}
