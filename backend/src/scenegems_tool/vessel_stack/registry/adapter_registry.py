"""Registry of layer specs, adapter specs, ruled-out connections and runtime bindings."""

from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple, TypeVar

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec, UnsupportedConnection
from scenegems_tool.vessel_stack.contracts.roles import LayerRef
from scenegems_tool.vessel_stack.registry.measured_capabilities import CapabilityMeasurement

# Runtime classes are bound through loaders so that resolving a stack never imports the
# code that builds it (Docker generators, MQTT clients).
RuntimeLoader = Callable[[], Any]
_Connection = Tuple[LayerRef, LayerRef]
_Spec = TypeVar("_Spec", LayerSpec, AdapterSpec)


class AdapterRegistry:
    def __init__(self, measurements: Optional[Mapping[str, CapabilityMeasurement]] = None):
        self._measurements: Dict[str, CapabilityMeasurement] = dict(measurements or {})
        self._layers: Dict[LayerRef, LayerSpec] = {}
        self._adapters: Dict[_Connection, AdapterSpec] = {}
        self._adapters_by_id: Dict[str, AdapterSpec] = {}
        self._unsupported: Dict[_Connection, UnsupportedConnection] = {}
        self._spec_ids: Set[str] = set()
        self._runtimes: Dict[str, RuntimeLoader] = {}

    def register_layer(self, spec: LayerSpec, runtime: Optional[RuntimeLoader] = None) -> LayerSpec:
        self._claim_id(spec.id)
        spec = self._measured(spec)
        self._layers[spec.layer] = spec
        self._bind(spec.id, runtime)
        return spec

    def register_adapter(self, spec: AdapterSpec, runtime: Optional[RuntimeLoader] = None) -> AdapterSpec:
        connection = (spec.source, spec.target)
        if connection in self._adapters:
            raise ValueError(f"Adapters {self._adapters[connection].id} and {spec.id} both connect {spec.source} to {spec.target}")
        if connection in self._unsupported:
            raise ValueError(f"Adapter {spec.id} connects {spec.source} to {spec.target}, which is declared unsupported")
        self._claim_id(spec.id)
        spec = self._measured(spec)
        self._adapters[connection] = spec
        self._adapters_by_id[spec.id] = spec
        self._bind(spec.id, runtime)
        return spec

    def declare_unsupported(self, connection: UnsupportedConnection) -> None:
        key = (connection.source, connection.target)
        if key in self._adapters:
            raise ValueError(f"{connection.source} to {connection.target} has adapter {self._adapters[key].id} and cannot be declared unsupported")
        self._unsupported[key] = connection

    def bind_runtime(self, spec_id: str, runtime: RuntimeLoader) -> None:
        if spec_id not in self._spec_ids:
            raise KeyError(f"No spec {spec_id} is registered")
        self._runtimes[spec_id] = runtime

    def layer(self, ref: LayerRef) -> Optional[LayerSpec]:
        return self._layers.get(ref)

    def adapter_between(self, source: LayerRef, target: LayerRef) -> Optional[AdapterSpec]:
        return self._adapters.get((source, target))

    def unsupported_between(self, source: LayerRef, target: LayerRef) -> Optional[UnsupportedConnection]:
        return self._unsupported.get((source, target))

    def adapter(self, adapter_id: str) -> AdapterSpec:
        return self._adapters_by_id[adapter_id]

    @property
    def layers(self) -> List[LayerSpec]:
        return list(self._layers.values())

    @property
    def adapters(self) -> List[AdapterSpec]:
        return list(self._adapters.values())

    def measurement(self, spec_id: str) -> Optional[CapabilityMeasurement]:
        return self._measurements.get(spec_id)

    def runtime(self, spec_id: str) -> Any:
        """The runtime class bound to a spec."""
        loader = self._runtimes.get(spec_id)
        if loader is None:
            raise LookupError(f"{spec_id} has no runtime implementation")
        return loader()

    def check_measurements(self) -> None:
        """Fail on measured entries that match no registered spec, since a typo would drop a measurement."""
        unknown = sorted(set(self._measurements) - self._spec_ids)
        if unknown:
            raise ValueError(f"Measured capabilities for unregistered specs: {', '.join(unknown)}")

    def _claim_id(self, spec_id: str) -> None:
        if spec_id in self._spec_ids:
            raise ValueError(f"Spec {spec_id} is already registered")
        self._spec_ids.add(spec_id)

    def _measured(self, spec: _Spec) -> _Spec:
        measurement = self._measurements.get(spec.id)
        if measurement is None:
            return spec
        return spec.with_capabilities(measurement.apply(spec.capabilities), measurement.notes)

    def _bind(self, spec_id: str, runtime: Optional[RuntimeLoader]) -> None:
        if runtime is not None:
            self._runtimes[spec_id] = runtime
