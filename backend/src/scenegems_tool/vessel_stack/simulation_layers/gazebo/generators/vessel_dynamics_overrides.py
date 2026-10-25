"""Loads the vessel dynamics override files (backend/assets/domain_config/vessel_dynamics/*.yaml).

Each file has two optional sections, both mappings of override key to number:

    vessel_types:            # by ConcreteVessel.type (the vessel type name)
      CargoShip:
        block_coefficient: 0.75
    vessel_ids:              # by ConcreteVessel.id
      3:
        max_thrust: 250000

The keys are the fields of DynamicsAssumptions and VesselDynamics. For one vessel the id
entry wins over the type entry, key by key. Unknown sections, keys, non-numeric values and
an entry defined in two files all fail loudly.
"""

import glob
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

import yaml

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import OVERRIDE_KEYS
from utils.file_system_utils import VESSEL_DYNAMICS_FOLDER

_SECTIONS = ("vessel_types", "vessel_ids")


@dataclass(frozen=True)
class VesselDynamicsOverrides:
    by_vessel_type: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    by_vessel_id: Mapping[int, Mapping[str, float]] = field(default_factory=dict)

    def for_vessel(self, vessel: ConcreteVessel) -> Dict[str, float]:
        return {**self.by_vessel_type.get(vessel.type, {}), **self.by_vessel_id.get(int(vessel.id), {})}


def _parse_entry(where: str, entry: Any) -> Dict[str, float]:
    if not isinstance(entry, Mapping):
        raise ValueError(f"{where}: expected a mapping of vessel dynamics keys to numbers")
    unknown = set(entry) - OVERRIDE_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown vessel dynamics keys {sorted(map(str, unknown))}; known keys: {sorted(OVERRIDE_KEYS)}")
    values = {}
    for key, value in entry.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where}: {key} must be a number, got {value!r}")
        values[key] = float(value)
    return values


def load_vessel_dynamics_overrides(folder: str = VESSEL_DYNAMICS_FOLDER) -> VesselDynamicsOverrides:
    by_section: Dict[str, Dict[Any, Dict[str, float]]] = {section: {} for section in _SECTIONS}
    for path in sorted(glob.glob(os.path.join(folder, "*.yaml"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, Mapping):
            raise ValueError(f"{name}: expected the sections {list(_SECTIONS)}")
        unknown_sections = set(data) - set(_SECTIONS)
        if unknown_sections:
            raise ValueError(f"{name}: unknown sections {sorted(map(str, unknown_sections))}; expected {list(_SECTIONS)}")
        for section in _SECTIONS:
            for key, entry in (data.get(section) or {}).items():
                key = int(key) if section == "vessel_ids" else str(key)
                if key in by_section[section]:
                    raise ValueError(f"{name}: {section} {key} is already defined in another vessel dynamics file")
                by_section[section][key] = _parse_entry(f"{name}: {section} {key}", entry)
    return VesselDynamicsOverrides(by_vessel_type=by_section["vessel_types"], by_vessel_id=by_section["vessel_ids"])
