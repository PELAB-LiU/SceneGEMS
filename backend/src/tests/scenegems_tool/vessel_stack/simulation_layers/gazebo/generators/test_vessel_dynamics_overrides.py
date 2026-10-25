"""Loading of the vessel dynamics override files: sections, precedence, and loud failures."""

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import VesselDynamicsOverrides, load_vessel_dynamics_overrides
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel
from utils.file_system_utils import VESSEL_DYNAMICS_FOLDER


def write(folder, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def test_the_shipped_folder_loads_and_holds_no_overrides_yet():
    overrides = load_vessel_dynamics_overrides(VESSEL_DYNAMICS_FOLDER)
    assert overrides.by_vessel_type == {}
    assert overrides.by_vessel_id == {}


def test_empty_folder_gives_no_overrides(tmp_path):
    assert load_vessel_dynamics_overrides(str(tmp_path)) == VesselDynamicsOverrides({}, {})


def test_type_and_id_sections_are_read(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coefficient: 0.75\nvessel_ids:\n  3:\n    max_thrust: 250000\n")
    overrides = load_vessel_dynamics_overrides(str(tmp_path))
    assert overrides.by_vessel_type == {"CargoShip": {"block_coefficient": 0.75}}
    assert overrides.by_vessel_id == {3: {"max_thrust": 250000.0}}


def test_id_entry_wins_over_the_type_entry_key_by_key():
    overrides = VesselDynamicsOverrides(
        by_vessel_type={"OSPassengerShip": {"block_coefficient": 0.7, "propeller_kt": 0.25}},
        by_vessel_id={0: {"block_coefficient": 0.8}},
    )
    assert overrides.for_vessel(make_vessel(0, True)) == {"block_coefficient": 0.8, "propeller_kt": 0.25}


def test_vessel_without_an_entry_gets_nothing():
    overrides = VesselDynamicsOverrides(by_vessel_type={"CargoShip": {"block_coefficient": 0.7}}, by_vessel_id={5: {"max_thrust": 1.0}})
    assert overrides.for_vessel(make_vessel(0, True)) == {}


def test_several_files_are_merged(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coefficient: 0.75\n")
    write(tmp_path, "b.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    overrides = load_vessel_dynamics_overrides(str(tmp_path))
    assert set(overrides.by_vessel_type) == {"CargoShip"}
    assert set(overrides.by_vessel_id) == {1}


def test_unknown_section_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessels:\n  1: {}\n")
    with pytest.raises(ValueError, match=r"a.yaml: unknown sections \['vessels'\]"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_unknown_key_fails_and_lists_the_known_ones(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coeficient: 0.75\n")
    with pytest.raises(ValueError, match=r"unknown vessel dynamics keys \['block_coeficient'\]; known keys:"):
        load_vessel_dynamics_overrides(str(tmp_path))


@pytest.mark.parametrize("value", ["heavy", "'1.5'", "true", "[1, 2]"])
def test_non_numeric_value_fails(tmp_path, value):
    write(tmp_path, "a.yaml", f"vessel_ids:\n  1:\n    max_thrust: {value}\n")
    with pytest.raises(ValueError, match="must be a number"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_entry_that_is_not_a_mapping_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1: 5\n")
    with pytest.raises(ValueError, match="expected a mapping of vessel dynamics keys to numbers"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_file_that_is_not_a_mapping_fails(tmp_path):
    write(tmp_path, "a.yaml", "- 1\n- 2\n")
    with pytest.raises(ValueError, match="expected the sections"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_an_entry_in_two_files_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    write(tmp_path, "b.yaml", "vessel_ids:\n  1:\n    max_thrust: 6\n")
    with pytest.raises(ValueError, match="b.yaml: vessel_ids 1 is already defined in another vessel dynamics file"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_integer_values_become_floats(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    value = load_vessel_dynamics_overrides(str(tmp_path)).by_vessel_id[1]["max_thrust"]
    assert isinstance(value, float)


def test_empty_sections_are_allowed(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types: {}\nvessel_ids:\n")
    assert load_vessel_dynamics_overrides(str(tmp_path)).by_vessel_id == {}
