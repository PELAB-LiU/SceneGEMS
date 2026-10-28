"""ManeuverStateMachine: one undetected maneuver per vessel at the start, and a state per vessel at every step."""

from concrete_level.colregs_monitoring.maneuver import ManeuverType, UndetectedManeuver
from concrete_level.colregs_monitoring.maneuver_context import ManeuverContextSet
from concrete_level.colregs_monitoring.maneuver_state_machine import ManeuverStateMachine
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants, monitored_run


def _scene():
    return monitored_run((3600.0, -3600.0), 1)[0].scene


def test_the_initial_state_set_has_an_undetected_maneuver_per_vessel():
    contexts = ManeuverContextSet.from_scene(_scene(), 5, constants())
    states = ManeuverStateMachine.create_initial_state_set(contexts)
    assert set(states) == {Relation(OWN_SHIP, OWN_SHIP), Relation(TARGET, TARGET)}
    for relation, state in states.items():
        assert isinstance(state, UndetectedManeuver)
        assert state.maneuver_context is contexts[relation]
        assert (state.maneuver_count, state.start_timestamp, state.current_timestamp) == (1, 5, 5)
        assert (state.distance_made, state.total_distance_made, state.previous_maneuver_type) == (0, 0, ManeuverType.UNDETECTED)
        assert state.heading_change.heading_diff_since_start == 0 and state.speed_change.speed_diff_since_start == 0


def test_an_empty_scene_set_has_no_states():
    assert ManeuverStateMachine.create_initial_state_set(ManeuverContextSet()) == {}


def test_a_step_gives_every_vessel_its_next_state_and_holds_straight_courses_undetected():
    run = monitored_run((3600.0, -3600.0), 3)
    current, next_result = run[1], run[2]
    contexts = ManeuverContextSet.from_scene(next_result.scene, 2, constants())
    states = ManeuverStateMachine.step(current, contexts, next_result.scene, 1)
    assert set(states) == set(contexts) == set(current.maneuver_state_set)
    for relation, state in states.items():
        assert state.maneuver_context is contexts[relation]
        assert state.type is ManeuverType.UNDETECTED
        assert state.current_timestamp == current.maneuver_state_set[relation].current_timestamp + 1
        assert state.start_timestamp == current.maneuver_state_set[relation].start_timestamp
