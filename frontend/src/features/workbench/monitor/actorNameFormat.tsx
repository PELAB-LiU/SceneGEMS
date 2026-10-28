import { Fragment, useMemo, type ReactNode } from "react";
import type { ActorStaticInfo } from "../../../domain/simulation/types";
import {
  ActorNamesContext,
  buildActorNameMap,
  relationParts,
  renderActorName,
  useActorNames,
} from "./actorNames";

export function ActorNamesProvider({
  actors,
  children,
}: {
  actors: ActorStaticInfo[] | undefined;
  children: ReactNode;
}) {
  const names = useMemo(() => buildActorNameMap(actors), [actors]);
  return <ActorNamesContext.Provider value={names}>{children}</ActorNamesContext.Provider>;
}

export function RelationLabel({ relationId }: { relationId: string }) {
  const names = useActorNames();
  const parts = relationParts(relationId, names);
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? " - " : null}
          {renderActorName(part)}
        </Fragment>
      ))}
    </>
  );
}
