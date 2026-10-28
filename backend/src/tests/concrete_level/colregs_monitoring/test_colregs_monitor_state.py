"""COLREGSMonitorStateSet: an actor violates a safety domain when any of its relations does."""

from types import SimpleNamespace

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorStateSet
from concrete_level.models.relation import Relation
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel

A, B, C = make_vessel(0, True), make_vessel(1, False), make_vessel(2, False)
AB, BC = Relation(A, B), Relation(B, C)


def _state(violates):
    return SimpleNamespace(actors_violate_safety_domain=violates)


def test_an_actor_violates_when_any_of_its_relations_does():
    collected = COLREGSMonitorStateSet.collect_actors_violate_safety_domain({AB: _state(True), BC: _state(False)})
    assert collected == {A: True, B: True, C: False}


def test_the_last_relation_does_not_decide_for_everybody():
    """Regression: a leaked loop variable once gave every actor the verdict of the last relation."""
    collected = COLREGSMonitorStateSet.collect_actors_violate_safety_domain({AB: _state(True), BC: _state(False)})
    assert collected[A] is True
    reversed_order = COLREGSMonitorStateSet.collect_actors_violate_safety_domain({BC: _state(False), AB: _state(True)})
    assert reversed_order == collected


def test_no_relations_means_no_violations():
    assert COLREGSMonitorStateSet.collect_actors_violate_safety_domain({}) == {}


def test_the_set_answers_per_actor_and_defaults_to_no_violation():
    states = {AB: _state(True)}
    state_set = COLREGSMonitorStateSet(states, COLREGSMonitorStateSet.collect_actors_violate_safety_domain(states))
    assert state_set.actor_violates_safety_domain(A) and state_set.actor_violates_safety_domain(B)
    assert not state_set.actor_violates_safety_domain(C)
    assert set(state_set) == {AB}
