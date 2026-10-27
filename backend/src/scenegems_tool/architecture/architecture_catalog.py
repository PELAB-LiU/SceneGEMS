"""The architecture documents of the system, built from the specs in code.

Four documents: the vessel stack (read from the adapter registry) and the trajectory generation, scene generation and
monitoring subsystems (read from their *_specs.py modules). A new implementation is declared where it lives, and the next
build shows it; nothing here lists implementations.
"""

from typing import Dict, Mapping, Optional

from scenegems_tool.architecture.architecture_model import ArchitectureDocument
from scenegems_tool.architecture.vessel_stack_description import vessel_stack_document
from scenegems_tool.subsystems.monitoring.monitoring_specs import monitoring_document
from scenegems_tool.subsystems.scene_generation.scene_generation_specs import scene_generation_document
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, check_measured_ids, default_measured_facts
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_specs import trajectory_generation_document


def build_architecture_documents(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> Dict[str, ArchitectureDocument]:
    """The documents by id, in the order the page shows them. measurements are the subsystem measured facts (the file's by default)."""
    measurements = default_measured_facts() if measurements is None else measurements
    subsystems = (
        trajectory_generation_document(measurements),
        scene_generation_document(measurements),
        monitoring_document(measurements),
    )
    check_measured_ids(measurements, (item.id for document in subsystems for item in (*document.nodes, *document.edges)))
    documents = (vessel_stack_document(), *subsystems)
    return {document.id: document for document in documents}
