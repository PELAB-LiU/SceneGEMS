import type { RuleEvaluation, RuleResult } from "../../../domain/simulation/types";

/** FAILED first, then not-yet-evaluated, then satisfied. */
const RESULT_RANK: Record<RuleResult, number> = {
  FAILED: 0,
  UNKNOWN: 1,
  PASSED: 2,
};

/** Failures first, then rules before suggestions, by number, vessel and title: one fixed order per frame. */
export function sortEvaluations(evaluations: RuleEvaluation[]): RuleEvaluation[] {
  return [...evaluations].sort((a, b) => {
    if (RESULT_RANK[a.result] !== RESULT_RANK[b.result]) {
      return RESULT_RANK[a.result] - RESULT_RANK[b.result];
    }
    if (a.kind !== b.kind) {
      return a.kind === "rule" ? -1 : 1;
    }
    if (a.ruleNumber !== b.ruleNumber) {
      return a.ruleNumber.localeCompare(b.ruleNumber, undefined, { numeric: true });
    }
    const bySubject = a.subjectActorName.localeCompare(b.subjectActorName);
    return bySubject !== 0 ? bySubject : a.title.localeCompare(b.title);
  });
}
