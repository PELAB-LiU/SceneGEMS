"""StandOnCoursePersistenceCondition (Rule 17): it binds the stand-on vessel of a live encounter, and nothing else."""

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.monitor_runs import TARGET, monitored_run

# The target crosses the own ship's bow from starboard: the own ship gives way, the target stands on.
CROSSING = (3600.0, -3600.0)
# The target crosses 600 m ahead of the own ship: never a collision course, so nobody stands on.
CLEAR_AHEAD = (3600.0, -3000.0)


def rule_17(result) -> COLREGSRuleResult:
    results = result.monitor_result_map_set.get_result(Relation(TARGET, TARGET))
    (value,) = [value for rule, value in results.items() if rule.rule_number == "17"]
    return value


def test_the_stand_on_vessel_fails_when_it_turns_in_a_live_encounter():
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    assert any(context.is_stand_on_actor(TARGET) for context in run[10].situation_context_set.values())
    assert rule_17(run[20]) == COLREGSRuleResult.UNKNOWN
    assert rule_17(run[40]) == COLREGSRuleResult.FAILED


def test_a_vessel_that_never_stands_on_may_turn():
    """Regression: the per-vessel rule judged every turn, so this target failed Rule 17 when it turned 450 s later."""
    run = monitored_run(CLEAR_AHEAD, 800, turn_at=700, turn_s=45)
    assert all(not context.is_stand_on_actor(TARGET) for result in run for context in result.situation_context_set.values())
    assert {rule_17(result) for result in run[1:]} == {COLREGSRuleResult.UNKNOWN}


def test_the_stand_on_vessel_holding_its_course_does_not_fail():
    run = monitored_run(CROSSING, 120)
    assert {rule_17(result) for result in run[1:]} == {COLREGSRuleResult.UNKNOWN}
