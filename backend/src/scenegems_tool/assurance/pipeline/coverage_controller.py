"""Which cases a class starts, completes and cuts, so the selected set does not depend on timing.

Cases of a class are numbered 0, 1, 2, ... and started in that order, each with its seed from
the campaign seed, the class and the index. The outcome of a case (complete, dropped) is a
function of its seed, so the selection below is too:

- A case whose runs all have their verdicts is ready, not complete. Walking the class's cases
  by index, a ready case is completed while fewer than quota cases are complete, and the
  walk stops at the first case still running. Once quota cases are complete the class is
  complete; started cases above that point are cancelled. A complete class has exactly its
  quota of complete cases, the first quota by index that did not drop or fail.
- A class is abandoned when its dropped and failed cases exceed its failure budget.
- A class keeps quota + spare cases complete or in flight, where spare is one more than its
  dropped cases so far, but never more than its failure budget left. Drops are replaced at
  once; the spare runs ahead in case another one drops, and grows when the class drops
  often. Started cases that were not cancelled never exceed quota + failure budget, so no
  case starts that could not be needed, and the case set stays a prefix of the indexes.
  Both rules keep the outcome independent of timing: a class is abandoned exactly when, in
  index order, more cases than its budget drop before quota cases complete.

Backpressure: a new case starts only while every stage has fewer queued jobs (and intents)
of the campaign than its cap.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from scenegems_tool.assurance.campaign.campaign_config import QueueDepthCaps
from scenegems_tool.assurance.pipeline.stage_graph import JOB_STAGES
from scenegems_tool.persistence.schema import CampaignClassState, CaseState, PipelineStage
from scenegems_tool.persistence.stores import CaseRecord, ClassRecord


def is_ready(case: CaseRecord) -> bool:
    """Every run of the active case has its verdict pending: the controller may complete it."""
    return case.state == CaseState.ACTIVE and case.stage == PipelineStage.VERDICT


@dataclass(frozen=True)
class ClassDecision:
    complete: Tuple[int, ...] = ()  # ready cases to complete now, in index order
    cancel: Tuple[int, ...] = ()  # active cases to cancel: above the quota, or the class is abandoned
    close: Optional[CampaignClassState] = None  # complete or abandoned
    reason: Optional[str] = None


def decide_class(cases: Sequence[CaseRecord], quota: int, failure_budget: int, dropped: int) -> ClassDecision:
    """The decision for one open class, from all its cases (any order) and its dropped count (dropped and failed)."""
    ordered = sorted(cases, key=lambda case: case.case_index)
    complete = sum(1 for case in ordered if case.state == CaseState.COMPLETE)
    to_complete: List[int] = []
    boundary: Optional[int] = None  # index of the case that brought the class to its quota
    count = 0
    for case in ordered:
        if case.state == CaseState.COMPLETE:
            count += 1
        elif case.state.is_final:
            continue
        elif is_ready(case) and count < quota:
            to_complete.append(case.case_id)
            count += 1
        else:
            break
        if count >= quota:
            boundary = case.case_index
            break
    if boundary is not None:
        cut = tuple(case.case_id for case in ordered if case.case_index > boundary and case.state == CaseState.ACTIVE)
        return ClassDecision(tuple(to_complete), cut, CampaignClassState.COMPLETE, f"{quota} complete cases up to index {boundary}")
    if dropped > failure_budget:
        rest = tuple(case.case_id for case in ordered if case.state == CaseState.ACTIVE and case.case_id not in to_complete)
        reason = f"{dropped} dropped or failed cases exceed the failure budget of {failure_budget} ({complete + len(to_complete)} of {quota} complete)"
        return ClassDecision(tuple(to_complete), rest, CampaignClassState.ABANDONED, reason)
    return ClassDecision(tuple(to_complete))


def spare_cases(record: ClassRecord) -> int:
    """Cases a class runs beyond its quota: one more than it dropped so far, within the failure budget left."""
    return max(0, min(record.failure_budget_left, record.dropped_count + 1))


def startable(record: ClassRecord) -> int:
    """How many more cases the open class may start now."""
    if record.state != CampaignClassState.OPEN or record.dropped_count > record.failure_budget:
        return 0
    return max(0, record.quota + spare_cases(record) - record.complete_count - record.in_flight_count)


@dataclass
class Backpressure:
    """The campaign's queued jobs per stage against the config's caps."""

    caps: QueueDepthCaps
    queued: Dict[PipelineStage, int] = field(default_factory=dict)

    def full_stages(self) -> List[PipelineStage]:
        return [stage for stage in JOB_STAGES if self.queued.get(stage, 0) >= self.caps.cap(stage)]

    def room_for_new_cases(self) -> int:
        """New cases that fit: each adds a scene generation job, and no stage may be at its cap."""
        if self.full_stages():
            return 0
        return self.caps.cap(PipelineStage.GENERATE_SCENE) - self.queued.get(PipelineStage.GENERATE_SCENE, 0)


def plan_new_cases(classes: Sequence[ClassRecord], next_indexes: Mapping[str, int], room: int) -> List[Tuple[str, int]]:
    """(class id, case index) of the cases to start: round robin over the classes in their order, each in index order, at most room."""
    budgets = {record.class_id: startable(record) for record in classes}
    indexes = {record.class_id: next_indexes.get(record.class_id, 0) for record in classes}
    planned: List[Tuple[str, int]] = []
    while len(planned) < room and any(budgets.values()):
        for record in classes:
            if len(planned) >= room:
                break
            if budgets[record.class_id] > 0:
                planned.append((record.class_id, indexes[record.class_id]))
                indexes[record.class_id] += 1
                budgets[record.class_id] -= 1
    return planned
