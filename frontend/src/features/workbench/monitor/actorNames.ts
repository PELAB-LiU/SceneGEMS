import { createContext, createElement, Fragment, useContext, type ReactNode } from "react";
import type { ActorStaticInfo } from "../../../domain/simulation/types";

/** Actor id to display name, so relation ids like "0->1" render as "OS_0 - TS_1". */
export type ActorNameMap = Readonly<Record<string, string>>;

export const ActorNamesContext = createContext<ActorNameMap>({});

export function useActorNames(): ActorNameMap {
  return useContext(ActorNamesContext);
}

export function buildActorNameMap(actors: ActorStaticInfo[] | undefined): ActorNameMap {
  const out: Record<string, string> = {};
  for (const actor of actors ?? []) {
    out[actor.id] = actor.name || actor.id;
  }
  return out;
}

export function relationParts(relationId: string, names: ActorNameMap): string[] {
  return relationId.split("->").map((id) => names[id] ?? id);
}

export function formatRelationId(relationId: string, names: ActorNameMap = {}): string {
  return relationParts(relationId, names).join(" - ");
}

export function renderActorName(name: string): ReactNode {
  const match = name.match(/^(.*)_(\d+)$/);
  if (!match) {
    return name;
  }
  const [, base, index] = match;
  return createElement(Fragment, null, base, createElement("sub", null, index));
}
