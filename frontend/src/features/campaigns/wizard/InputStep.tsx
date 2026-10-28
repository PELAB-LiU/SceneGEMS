import { useEffect, useState } from "react";
import { useOperatorClient } from "../useCampaignData";
import { ItemInput } from "./ItemInput";
import { ScenarioFiles } from "./ScenarioFiles";
import { ScopeStep } from "./ScopeStep";
import { inputKindOf } from "./stepPlan";
import type { CatalogState, StepProps } from "./stepTypes";

const CLOCK_MS = 60_000;

/** The time, refreshed every minute, for the expiry notes of uploaded files. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/**
 * Input: what the first step starts from. Scene generation takes classes of the catalog and/or
 * functional scenario files; trajectory generation takes scenes and simulation takes trajectories,
 * from Campaign History or uploaded files.
 */
export function InputStep(props: StepProps & { catalog: CatalogState }) {
  const client = useOperatorClient();
  const now = useNow();
  if (inputKindOf(props.draft.steps) !== "catalog_or_scenarios") {
    return <ItemInput draft={props.draft} update={props.update} reasons={props.reasons} client={client} now={now} />;
  }
  return (
    <div className="wiz-step">
      <ScenarioFiles draft={props.draft} update={props.update} reasons={props.reasons} client={client} now={now} />
      <ScopeStep {...props} />
    </div>
  );
}
