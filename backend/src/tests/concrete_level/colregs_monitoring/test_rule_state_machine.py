"""RuleStateMachine: rule results follow the active rules, in a fixed order."""

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMap, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import COLREGSRule
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import COLREGSRuleConditionMap, COLREGSRuleConditionMapSet
from concrete_level.colregs_monitoring.rule_state_machine import RuleStateMachine
from concrete_level.models.relation import Relation
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run

A, B, C = make_vessel(0, True), make_vessel(1, False), make_vessel(2, False)
AB, BC, AA = Relation(A, B), Relation(B, C), Relation(A, A)
UNKNOWN, PASSED, FAILED = COLREGSRuleResult.UNKNOWN, COLREGSRuleResult.PASSED, COLREGSRuleResult.FAILED


def rule(relation: Relation, number: str) -> COLREGSRule:
    return COLREGSRule(relation, number, f"title {number}", "")


def rules(**by_relation) -> COLREGSRuleConditionMapSet:
    relations = {"ab": AB, "bc": BC, "aa": AA}
    return COLREGSRuleConditionMapSet({relations[name]: COLREGSRuleConditionMap({rule(relations[name], number): None for number in numbers}) for name, numbers in by_relation.items()})


def results(**by_relation) -> COLREGSRuleResultMapSet:
    relations = {"ab": AB, "bc": BC, "aa": AA}
    return COLREGSRuleResultMapSet({relations[name]: COLREGSRuleResultMap({rule(relations[name], number): value for number, value in items}) for name, items in by_relation.items()})


def test_a_new_rule_starts_unknown_and_a_kept_rule_keeps_its_result():
    after = RuleStateMachine.transition_rule_results(rules(ab=["8"]), results(ab=[("8", FAILED)]), rules(ab=["8", "16"]))
    assert dict(after[AB]) == {rule(AB, "8"): FAILED, rule(AB, "16"): UNKNOWN}


def test_a_rule_that_ends_undecided_passes_and_a_failure_stays():
    after = RuleStateMachine.transition_rule_results(rules(ab=["8", "16"]), results(ab=[("8", UNKNOWN), ("16", FAILED)]), rules())
    assert dict(after[AB]) == {rule(AB, "8"): PASSED, rule(AB, "16"): FAILED}


def test_relations_follow_their_actor_ids_and_new_rules_their_definition_order():
    """Set order changed with the hash seed, so the monitor listed the same rules in different orders."""
    after = RuleStateMachine.transition_rule_results(rules(), results(), rules(bc=["17", "8", "16"], aa=["8"], ab=["16", "8"]))
    assert list(after) == [AA, AB, BC]
    assert [item.rule_number for item in after[BC]] == ["17", "8", "16"]


def test_a_monitored_run_reports_the_same_rule_order_every_time():
    run = monitored_run((3600.0, -3600.0), 60)
    orders = {tuple((str(relation), tuple(rule.name for rule in result_map)) for relation, result_map in result.monitor_result_map_set.items()) for result in run[5:]}
    assert len(orders) == 1
