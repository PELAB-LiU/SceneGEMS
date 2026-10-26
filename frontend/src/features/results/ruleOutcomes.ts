/**
 * A verdict's `rule_outcomes` as the monitor summarizes it (`subsystems/monitoring/rule_outcomes.py`):
 * relation, then rule, then outcome (`passed` or `failed`) to the first timestamp it held. A rule
 * that failed stays failed, even when it passed earlier.
 */

export interface RuleOutcomeRow {
  relation: string;
  rule: string;
  outcome: "failed" | "passed" | "undecided";
  /** Seconds of the first failure, when it failed. */
  failedAt: number | null;
  /** Seconds of the first pass, when it passed. */
  passedAt: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function seconds(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Rows of the outcomes, failed rules first, then by relation and rule. */
export function ruleOutcomeRows(outcomes: Record<string, unknown>): RuleOutcomeRow[] {
  const rows: RuleOutcomeRow[] = [];
  for (const [relation, rules] of Object.entries(outcomes)) {
    if (!isRecord(rules)) {
      continue;
    }
    for (const [rule, byOutcome] of Object.entries(rules)) {
      const failedAt = isRecord(byOutcome) ? seconds(byOutcome.failed) : null;
      const passedAt = isRecord(byOutcome) ? seconds(byOutcome.passed) : null;
      rows.push({
        relation,
        rule,
        outcome: failedAt !== null ? "failed" : passedAt !== null ? "passed" : "undecided",
        failedAt,
        passedAt,
      });
    }
  }
  const order = { failed: 0, undecided: 1, passed: 2 };
  return rows.sort((a, b) => order[a.outcome] - order[b.outcome] || a.relation.localeCompare(b.relation) || a.rule.localeCompare(b.rule));
}
