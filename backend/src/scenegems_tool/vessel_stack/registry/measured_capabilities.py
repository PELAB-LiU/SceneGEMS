"""Loads measured_capabilities.yaml, the single data location for measured capability values."""

import dataclasses
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import yaml

from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier

MEASURED_CAPABILITIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measured_capabilities.yaml")


def _optional_float(value: Any) -> Optional[float]:
    return None if value is None else float(value)


_CAPABILITY_PARSERS: Dict[str, Callable[[Any], Any]] = {
    "faster_than_real_time": bool,
    "lockstep": bool,
    "repeatability_tier": RepeatabilityTier,
    "exact_up_to_speedup": _optional_float,
    "wind": EnvironmentSupport,
    "waves": EnvironmentSupport,
    "max_speedup": _optional_float,
}
_RECORD_FIELDS = {"notes", "deviation_bounds_m", "evidence"}


@dataclass(frozen=True)
class CapabilityMeasurement:
    spec_id: str
    overrides: Tuple[Tuple[str, Any], ...]  # (Capabilities field, measured value)
    notes: Tuple[Tuple[str, str], ...] = ()
    deviation_bounds_m: Tuple[Tuple[float, float], ...] = ()  # (speedup, max deviation in meters)
    evidence: str = ""

    def apply(self, capabilities: Capabilities) -> Capabilities:
        return dataclasses.replace(capabilities, **dict(self.overrides))


def parse_capability_measurement(spec_id: str, entry: Mapping[str, Any]) -> CapabilityMeasurement:
    unknown = set(entry) - set(_CAPABILITY_PARSERS) - _RECORD_FIELDS
    if unknown:
        raise ValueError(f"{spec_id}: unknown measured capability fields {sorted(unknown)}")
    overrides = tuple((name, parse(entry[name])) for name, parse in _CAPABILITY_PARSERS.items() if name in entry)
    notes = tuple((str(name), str(text)) for name, text in (entry.get("notes") or {}).items())
    bounds = tuple(sorted((float(speedup), float(deviation)) for speedup, deviation in (entry.get("deviation_bounds_m") or {}).items()))
    return CapabilityMeasurement(spec_id=spec_id, overrides=overrides, notes=notes, deviation_bounds_m=bounds, evidence=str(entry.get("evidence", "")).strip())


def load_capability_measurements(path: str = MEASURED_CAPABILITIES_FILE) -> Dict[str, CapabilityMeasurement]:
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return {str(spec_id): parse_capability_measurement(str(spec_id), entry or {}) for spec_id, entry in data.items()}
