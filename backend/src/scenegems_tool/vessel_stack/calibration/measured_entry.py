"""Measurement results in the shape of registry/measured_capabilities.yaml.

An entry is a spec id and the fields the registry loader accepts for it (see the header of
measured_capabilities.yaml). Every entry is checked with the loader's own parser before it is
rendered, so a field name that the registry would reject fails here, not when the file is
merged. Several measurements of one spec combine conservatively: the largest deviation and the
weaker repeatability tier win, and a speed limit is the highest speedup that tracked its request.
"""

import datetime
import math
import platform
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import yaml

from scenegems_tool.vessel_stack.contracts.capabilities import RepeatabilityTier, weaker_tier
from scenegems_tool.vessel_stack.registry.catalog import default_registry
from scenegems_tool.vessel_stack.registry.measured_capabilities import CapabilityMeasurement, parse_capability_measurement


def host_label() -> str:
    """A label for the machine a pace was measured on: the value of host_max_speedup."""
    return f"{platform.node()}_{platform.system().lower()}"


def today() -> str:
    return datetime.date.today().isoformat()


@dataclass
class MeasuredEntry:
    spec_id: str
    fields: Dict[str, Any] = field(default_factory=dict)

    def parsed(self) -> CapabilityMeasurement:
        """The entry as the registry loader reads it. Raises for an unknown field or value."""
        return parse_capability_measurement(self.spec_id, self.fields)

    def check_registered(self) -> None:
        """Fail when no spec of the default registry has this id, as the registry build would."""
        registry = default_registry()
        known = {spec.id for spec in registry.layers} | {spec.id for spec in registry.adapters}
        if self.spec_id not in known:
            raise ValueError(f"No registered spec {self.spec_id}; known ids: {', '.join(sorted(known))}")


def _merge_bounds(first: Mapping[Any, float], second: Mapping[Any, float]) -> Dict[Any, float]:
    merged = dict(first)
    for speedup, deviation in second.items():
        merged[speedup] = max(merged.get(speedup, deviation), deviation)
    return dict(sorted(merged.items()))


def _merge_layer_bounds(first: Mapping[str, Mapping[Any, float]], second: Mapping[str, Mapping[Any, float]]) -> Dict[str, Dict[Any, float]]:
    layers = {layer_id: dict(bounds) for layer_id, bounds in first.items()}
    for layer_id, bounds in second.items():
        layers[layer_id] = _merge_bounds(layers.get(layer_id, {}), bounds)
    return layers


def _merge_host_limits(first: Mapping[str, float], second: Mapping[str, float]) -> Dict[str, float]:
    hosts = dict(first)
    for host, limit in second.items():
        hosts[host] = max(hosts.get(host, limit), limit)
    return hosts


def _weaker_tier_name(first: str, second: str) -> str:
    return weaker_tier(RepeatabilityTier(first), RepeatabilityTier(second)).value


def _highest_tracked(first: Optional[float], second: Optional[float]) -> Optional[float]:
    """A speed limit is the highest speedup that tracked its request, so runs at several speedups keep the highest."""
    if first is None or second is None:
        return first if second is None else second
    return max(first, second)


def _lowest_exact(first: Optional[float], second: Optional[float]) -> Optional[float]:
    """Bit-identical up to the lowest speedup at which a run was not, so the smaller bound is kept."""
    return None if first is None or second is None else min(first, second)


# How two measurements of one field combine; a field that is not listed takes the later value.
_COMBINE: Dict[str, Callable[[Any, Any], Any]] = {
    "deviation_bounds_m": _merge_bounds,
    "deviation_bounds_m_by_layer": _merge_layer_bounds,
    "host_max_speedup": _merge_host_limits,
    "repeatability_tier": _weaker_tier_name,
    "max_speedup": _highest_tracked,
    "exact_up_to_speedup": _lowest_exact,
    "notes": lambda first, second: {**first, **second},
    "evidence": lambda first, second: f"{first} {second}",
}


def merge_entries(entries: Iterable[MeasuredEntry]) -> List[MeasuredEntry]:
    """One entry per spec id, in first-seen order, combining repeated measurements conservatively."""
    merged: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        entry.parsed()
        target = merged.setdefault(entry.spec_id, {})
        for name, value in entry.fields.items():
            target[name] = _COMBINE.get(name, lambda _first, later: later)(target[name], value) if name in target else value
    return [MeasuredEntry(spec_id, fields) for spec_id, fields in merged.items()]


def _plain(value: Any) -> Any:
    """Python numbers and strings only, so the YAML carries no numpy tags."""
    if isinstance(value, Mapping):
        return {_plain(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        return _plain(value.item())
    if isinstance(value, float) and not math.isinf(value):
        return round(value, 6)
    return value


def render_yaml(entries: Iterable[MeasuredEntry], header: str = "") -> str:
    """The entries as YAML, in the shape of measured_capabilities.yaml (one top-level key per spec id)."""
    merged = merge_entries(entries)
    data = {entry.spec_id: _plain(entry.fields) for entry in merged}
    comment = "".join(f"# {line}\n" if line else "#\n" for line in header.splitlines())
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=100, allow_unicode=True)
    return comment + ("\n" if comment else "") + body


def write_yaml(path: str, entries: Iterable[MeasuredEntry], header: str = "") -> str:
    """Render, check that the loader accepts the text, and write it. Returns the text."""
    text = render_yaml(entries, header)
    for spec_id, entry in (yaml.safe_load(text) or {}).items():
        parse_capability_measurement(str(spec_id), entry or {})
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    return text


def evidence(method: str, **details: Any) -> str:
    """The evidence string of an entry: date, host and what was run."""
    parts = ", ".join(f"{name.replace('_', ' ')} {value}" for name, value in details.items())
    return f"Calibration {today()} on {host_label()}: {method}" + (f" ({parts})." if parts else ".")
