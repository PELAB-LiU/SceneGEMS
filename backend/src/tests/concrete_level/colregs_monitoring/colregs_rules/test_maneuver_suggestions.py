"""ManeuverSuggestions: merging by intersection, uniting, the allowed maneuvers and the suggested heading range."""

import random

from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.concrete_level.colregs_monitoring.monitor_runs import constants

A, B = make_vessel(0, True), make_vessel(1, False)
LEFT, RIGHT = ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT
PERSIST, UNDETECTED = ManeuverType.PERSISTING_COURSE, ManeuverType.UNDETECTED


def test_merge_intersects_shared_actors_and_keeps_the_others():
    first = ManeuverSuggestions({A: {LEFT, PERSIST}}, {A: "first"})
    second = ManeuverSuggestions({A: {LEFT, RIGHT}, B: {RIGHT}}, {A: "second", B: "only second"})
    merged = first.merge(second)
    assert dict(merged) == {A: {LEFT}, B: {RIGHT}}
    assert merged.get_info(A) == "first\nsecond" and merged.get_info(B) == "only second"


def test_merge_with_nothing_changes_nothing():
    suggestions = ManeuverSuggestions({A: {LEFT}}, {A: "info"})
    assert dict(suggestions.merge(ManeuverSuggestions())) == {A: {LEFT}}
    assert dict(ManeuverSuggestions().merge(suggestions)) == {A: {LEFT}}


def test_union_joins_the_sets_and_the_non_empty_infos():
    first = ManeuverSuggestions({A: {LEFT}}, {A: "first"})
    second = ManeuverSuggestions({A: {RIGHT}, B: {PERSIST}}, {B: "second"})
    united = first.union(second)
    assert dict(united) == {A: {LEFT, RIGHT}, B: {PERSIST}}
    assert united.get_info(A) == "first" and united.get_info(B) == "second"


def test_the_default_suggestions_are_not_shared_between_instances():
    ManeuverSuggestions()[A] = {LEFT}
    assert dict(ManeuverSuggestions()) == {}


def test_all_maneuvers_of_an_unknown_actor_are_every_detected_type():
    assert ManeuverSuggestions().get_all_maneuvers(A) == {LEFT, RIGHT, PERSIST}
    assert ManeuverSuggestions({A: {LEFT, UNDETECTED}}).get_all_maneuvers(A) == {LEFT}


def test_get_info_of_an_actor_without_info_is_empty():
    assert ManeuverSuggestions({A: {LEFT}}).get_info(A) == ""


def test_a_random_maneuver_comes_from_the_suggestion_and_never_is_undetected():
    random.seed(7)
    suggestions = ManeuverSuggestions({A: {LEFT, RIGHT, UNDETECTED}})
    assert {suggestions.get_random_maneuver(A) for _ in range(40)} == {LEFT, RIGHT}


def test_a_random_maneuver_with_nothing_suggested_falls_back_to_a_detected_type():
    random.seed(7)
    assert ManeuverSuggestions({A: {UNDETECTED}}).get_random_maneuver(A) in {LEFT, RIGHT, PERSIST}


def test_the_suggested_heading_range_is_the_union_of_the_ranges_of_the_maneuvers():
    step = A.get_max_heading_step(1.0)
    both = ManeuverSuggestions({A: {LEFT, RIGHT}}).get_suggested_range_of_heading_change(A, 1.0, constants())
    assert both.contains(step) and both.contains(-step) and not both.contains(0.0)
    left = ManeuverSuggestions({A: {LEFT}}).get_suggested_range_of_heading_change(A, 1.0, constants())
    assert left.contains(step) and not left.contains(-step)
    persisting = ManeuverSuggestions({A: {PERSIST}}).get_suggested_range_of_heading_change(A, 1.0, constants())
    assert persisting.contains(0.0) and not persisting.contains(step)
