import { describe, expect, it } from "vitest";
import { ruleOutcomeRows } from "./ruleOutcomes";

describe("rule outcomes", () => {
  it("reads relation, rule and outcome times, failed rules first", () => {
    const rows = ruleOutcomeRows({
      "0->1": {
        "Rule 8: Passing at a Safe Distance": { passed: 0 },
        "Rule 16: Give-Way": { passed: 0, failed: 31.5 },
      },
      "0->2": { "Rule 17: Stand-On": { failed: 12 } },
    });
    expect(rows.map((row) => [row.relation, row.rule, row.outcome, row.failedAt, row.passedAt])).toEqual([
      ["0->1", "Rule 16: Give-Way", "failed", 31.5, 0],
      ["0->2", "Rule 17: Stand-On", "failed", 12, null],
      ["0->1", "Rule 8: Passing at a Safe Distance", "passed", null, 0],
    ]);
  });

  it("keeps a rule with no decided outcome and skips what is not an outcome map", () => {
    const rows = ruleOutcomeRows({ "0->1": { "Rule 8": {} }, odd: "failed", list: [1, 2] });
    expect(rows).toEqual([{ relation: "0->1", rule: "Rule 8", outcome: "undecided", failedAt: null, passedAt: null }]);
    expect(ruleOutcomeRows({})).toEqual([]);
  });
});
