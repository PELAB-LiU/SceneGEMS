"""How a case moves: one job event at a time, in the engine's transaction, with optimistic versions.

A case starts active at generate_scene and moves through the stage graph as its jobs
succeed: each success records what it produced (artifact references, run records, pending
verdicts) in the case's progress and writes the intents of the jobs that became due. Every
move goes through CaseStore.move_case with the version the case was read at.

It leaves the pipeline early as

    dropped    the scene is invalid, or the trajectory generator found no trajectory or no
               complete one (the reason is recorded; trajectories_complete says which)
    failed     a job ended failed (out of attempts, or a failure that is not retryable), was
               cancelled by someone else, or returned a result its stage cannot use; the case
               is quarantined with the error
    cancelled  the campaign stopped, or the coverage controller cut it (above the quota, or
               its class was abandoned)

Dropped and failed cases count against their class's failure budget (the class's dropped
count). A final case keeps its state; later events of its jobs change nothing, and the jobs
it still has are cancelled.

Events are processed once: the step of an event already in the case's progress is skipped,
so a job with several terminal-looking events (an expired lease, then a failure) is handled
once.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import RetentionPolicy
from scenegems_tool.assurance.pipeline import retention
from scenegems_tool.assurance.pipeline.campaign_context import CampaignContext, CampaignContexts
from scenegems_tool.assurance.pipeline.payload_builder import PayloadError
from scenegems_tool.assurance.pipeline.pipeline_queries import job_facts, unfinished_jobs_of_cases
from scenegems_tool.assurance.pipeline.stage_graph import SCENE_STEP, TRAJECTORIES_STEP, CaseProgress, Step
from scenegems_tool.assurance.pipeline.verdicts import (
    ResultError,
    is_sensitive,
    new_calibration_result,
    new_run_record,
    new_verdict,
    pending_from_live,
    pending_from_post_hoc,
    pending_unmonitored,
    record_references,
    release_job_references,
)
from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import ArtifactHolderKind, CaseState, JobEventKind, MonitorImplementation, PipelineStage, VerdictState
from scenegems_tool.persistence.stores import UNSET, AssuranceStores, CaseConflict, CaseRecord, NewCase, PipelineJobEvent

logger = logging.getLogger(__name__)

SUCCEEDED, FAILED, CANCELLED = "succeeded", "failed", "cancelled"


@dataclass
class StepOutbox:
    """What a step of the engine leaves to do after its transaction, and what it touched."""

    jobs_to_cancel: Dict[str, str] = field(default_factory=dict)  # job id to the reason
    touched_classes: Set[Tuple[str, str]] = field(default_factory=set)  # (campaign id, class id) whose cases changed
    events_applied: int = 0
    cases_started: int = 0

    def cancel(self, job_ids, reason: str) -> None:
        for job_id in job_ids:
            self.jobs_to_cancel.setdefault(job_id, reason)

    def snapshot(self) -> tuple:
        return dict(self.jobs_to_cancel), set(self.touched_classes), self.events_applied, self.cases_started

    def restore(self, saved: tuple) -> None:
        jobs, touched, self.events_applied, self.cases_started = saved
        self.jobs_to_cancel, self.touched_classes = dict(jobs), set(touched)


def _outcome_of(event: PipelineJobEvent) -> Optional[str]:
    """succeeded, failed or cancelled when the event ends its job; None for an expired lease that requeued it."""
    if event.kind == JobEventKind.SUCCEEDED:
        return SUCCEEDED
    if event.kind == JobEventKind.FAILED or (event.kind == JobEventKind.EXPIRED and event.job_state == JobState.FAILED):
        return FAILED
    if event.kind == JobEventKind.CANCELLED:
        return CANCELLED
    return None


class CaseMachine:
    def __init__(self, stores: AssuranceStores, session: Session, contexts: CampaignContexts, outbox: StepOutbox):
        self.stores = stores
        self.session = session
        self.contexts = contexts
        self.outbox = outbox

    # Starting cases

    def start_cases(self, context: CampaignContext, planned: List[Tuple[str, int]]) -> List[CaseRecord]:
        """Creates the planned cases (class id, index) with their seeds and the intents of their scene generation jobs."""
        if not planned:
            return []
        version = context.campaign.config_version
        new_cases = [NewCase(class_id=class_id, case_index=index, seed=context.config.case_seed(class_id, index), config_version=version) for class_id, index in planned]
        created = self.stores.cases.create_cases(context.campaign_id, new_cases, session=self.session)
        for case in created:
            self.outbox.touched_classes.add((context.campaign_id, case.class_id))
            try:
                payload = context.builder.scene_generation(case.class_id, context.content_hashes[case.class_id], case.seed)
                self._intents(context, case, [(SCENE_STEP, payload)])
            except PayloadError as error:
                self.end(context, case, CaseState.FAILED, f"the scene generation payload could not be built: {error}")
        self.outbox.cases_started += len(created)
        return created

    # Events

    def apply(self, event: PipelineJobEvent) -> None:
        pipeline_job = event.pipeline_job
        outcome = _outcome_of(event)
        if outcome is None:
            return
        case = self.stores.cases.get_case(pipeline_job.case_id, session=self.session)
        if case is None:
            return
        context = self.contexts.get(pipeline_job.campaign_id, self.session, case.config_version)
        if context is None:
            return
        if case.state.is_final:
            # A job of an ended case: its results are not needed, unless the campaign keeps everything
            if outcome == SUCCEEDED and context.config.policy.retention != RetentionPolicy.ALL:
                release_job_references(self.stores, self.session, event.job_id)
            return
        step = Step.of(pipeline_job.stage, pipeline_job.run_index, pipeline_job.repeat_index)
        progress = CaseProgress(case.progress)
        if progress.handled(step):
            return
        self.outbox.events_applied += 1
        progress.mark(step, outcome)
        if outcome != SUCCEEDED:
            error = event.job_error or event.detail.get("reason") or "no error given"
            verb = "was cancelled" if outcome == CANCELLED else "failed"
            self.end(context, case, CaseState.FAILED, f"{step.name} job {event.job_id} {verb}: {error}", progress)
            return
        result = event.job_result or {}
        try:
            handler = {
                PipelineStage.GENERATE_SCENE: self._scene_generated,
                PipelineStage.GENERATE_TRAJECTORIES: self._trajectories_generated,
                PipelineStage.SIMULATE: self._simulated,
                PipelineStage.MONITOR: self._monitored,
                PipelineStage.CALIBRATE: self._calibrated,
            }[step.stage]
            handler(context, case, progress, step, event, result)
        except (ResultError, PayloadError) as error:
            self.end(context, case, CaseState.FAILED, f"{step.name} job {event.job_id}: {error}", progress)

    def _scene_generated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        roles = record_references(self.stores, self.session, result, ArtifactHolderKind.CASE, case.case_id, context.campaign_id, event.job_id)
        scene = roles.get("scene", UNSET)
        if not result.get("valid") or result.get("evaluation_data") is None:
            self.end(context, case, CaseState.DROPPED, "the scene generation found no valid scene", progress, scene_artifact=scene)
            return
        payload = context.builder.trajectory_generation(case.seed, result)
        case = self._save(context, case, progress, scene_artifact=scene)
        self._intents(context, case, [(TRAJECTORIES_STEP, payload)])

    def _trajectories_generated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        roles = record_references(self.stores, self.session, result, ArtifactHolderKind.CASE, case.case_id, context.campaign_id, event.job_id)
        trajectories = roles.get("trajectory_data", UNSET)
        valid, complete = bool(result.get("valid")), bool(result.get("complete"))
        if not valid or result.get("trajectory_data") is None:
            reason = "the trajectory generator found no trajectories" + (f": {result['error_message']}" if result.get("error_message") else "")
            self.end(context, case, CaseState.DROPPED, reason, progress, trajectories_artifact=trajectories, trajectories_complete=False)
            return
        if not complete:
            self.end(
                context,
                case,
                CaseState.DROPPED,
                "the trajectory generator found no complete trajectories (only the best partial path)",
                progress,
                trajectories_artifact=trajectories,
                trajectories_complete=False,
            )
            return
        payloads = [(simulate, context.builder.simulation(case.seed, simulate.run_index, result)) for simulate in context.graph.simulate_steps()]
        case = self._save(context, case, progress, trajectories_artifact=trajectories, trajectories_complete=True)
        self._intents(context, case, payloads)

    def _simulated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        run_index, repeat_index = step.run_index, step.repeat_index
        run = context.graph.run(run_index)
        if result.get("trajectories") is None and (run.monitor == MonitorImplementation.POST_HOC or context.graph.needs_calibration(run_index)):
            raise ResultError("the simulation returned no trajectories")
        facts = job_facts(self.session, [event.job_id]).get(event.job_id)
        tier = (result.get("run_record") or {}).get("repeatability_tier")
        record = self.stores.results.add_run_record(
            new_run_record(
                case_id=case.case_id,
                run_index=run_index,
                repeat_index=repeat_index,
                generator=context.config.trajectories.generator,
                trajectories_complete=bool(case.trajectories_complete),
                stack=context.stack(run_index),
                environment=context.environment(run_index),
                seed=run.seed_for(case.seed, run_index),
                simulation_result=result,
                input_trajectories_hash=case.trajectories_artifact,
                job_id=event.job_id,
                node_id=facts.lease_owner if facts is not None else event.node_id,
                fingerprints=facts.required_fingerprints if facts is not None else {},
                durations_s=facts.durations_s() if facts is not None else {},
                tier=tier,
            ),
            session=self.session,
        )
        record_references(self.stores, self.session, result, ArtifactHolderKind.RUN, record.run_record_id, context.campaign_id, event.job_id)
        progress.set_run_record(run_index, repeat_index, record.run_record_id)
        if repeat_index == 0:
            state = progress.run(run_index)
            state["tier"] = record.repeatability_tier
            if run.monitor == MonitorImplementation.LIVE:
                state["verdict"] = pending_from_live(result)
            elif run.monitor == MonitorImplementation.EMPTY:
                state["verdict"] = pending_unmonitored()
        due = []
        for next_step in context.graph.steps_after_simulation(progress, run_index, repeat_index):
            if next_step.stage == PipelineStage.MONITOR:
                due.append((next_step, context.builder.post_hoc_monitoring(f"{context.scenario_name(case)}#run{run_index}", result)))
            else:
                due.append((next_step, context.builder.calibration(context.scenario_name(case), context.stack(run_index), self._repeat_results(case, run_index, event.job_id, result))))
        case = self._save(context, case, progress)
        self._intents(context, case, due)

    def _monitored(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        pending = pending_from_post_hoc(result)
        run_record_id = progress.run_record_id(step.run_index, 0)
        if run_record_id is not None:
            record_references(self.stores, self.session, result, ArtifactHolderKind.RUN, run_record_id, context.campaign_id, event.job_id)
        progress.run(step.run_index)["verdict"] = pending
        self._save(context, case, progress)

    def _calibrated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        calibration = new_calibration_result(result, context.stack(step.run_index), context.run_fingerprints(), context.environment(step.run_index), context.campaign_id)
        stored = self.stores.calibrations.upsert(calibration, session=self.session)
        state = progress.run(step.run_index)
        state["calibrated"] = True
        state["calibration"] = {"calibration_id": stored.calibration_id, "exact": stored.exact, "deviation_bound_m": stored.deviation_bound_m}
        self._save(context, case, progress)

    def _repeat_results(self, case: CaseRecord, run_index: int, current_job_id: str, current: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        """The simulation results of every repeat of the run, in repeat order."""
        jobs = [job for job in self.stores.pipeline.pipeline_jobs_of_case(case.case_id, session=self.session) if job.stage == PipelineStage.SIMULATE and job.run_index == run_index]
        facts = job_facts(self.session, [job.job_id for job in jobs if job.job_id is not None and job.job_id != current_job_id])
        results = []
        for job in sorted(jobs, key=lambda job: job.repeat_index):
            result = current if job.job_id == current_job_id else (facts.get(job.job_id).result if job.job_id in facts else None)
            if result is None or result.get("trajectories") is None:
                raise ResultError(f"repeat {job.repeat_index} of run {run_index} has no trajectories to calibrate with")
            results.append(result)
        return results

    # Ends

    def complete(self, context: CampaignContext, case: CaseRecord) -> CaseRecord:
        """Writes the ready case's verdicts, applies retention and completes it."""
        progress = CaseProgress(case.progress)
        states: Dict[int, VerdictState] = {}
        run_records: Dict[int, List[int]] = {}
        for run_index in range(len(context.graph.runs)):
            pending = progress.pending_verdict(run_index)
            if pending is None:
                raise ValueError(f"case {case.case_id} has no verdict for run {run_index}")
            tier = progress.run(run_index).get("tier")
            sensitive = is_sensitive(self.stores, self.session, tier, context.stack(run_index), context.run_fingerprints())
            verdict = self.stores.results.add_verdict(new_verdict(case.case_id, run_index, pending, progress.run_record_id(run_index, 0), sensitive), session=self.session)
            states[run_index] = verdict.state
            run_records[run_index] = sorted(progress.run(run_index).get("run_records", {}).values())
        retention.apply_on_verdicts(self.stores, self.session, context.config.policy.retention, case.case_id, states, run_records)
        moved = self._move(case, state=CaseState.COMPLETE, stage=PipelineStage.VERDICT, reason=None)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        return moved

    def cancel(self, context: CampaignContext, case: CaseRecord, reason: str) -> CaseRecord:
        moved = self.end(context, case, CaseState.CANCELLED, reason)
        policy: RetentionPolicy = context.config.policy.retention
        retention.apply_on_cancel(self.stores, self.session, policy, case.case_id, CaseProgress(case.progress).run_record_ids())
        return moved

    def end(self, context: CampaignContext, case: CaseRecord, state: CaseState, reason: str, progress: Optional[CaseProgress] = None, **fields: Any) -> CaseRecord:
        """Moves the case to a final state with its reason; its unfinished jobs are cancelled after the transaction."""
        if progress is not None:
            fields["progress"] = progress.to_json()
        moved = self._move(case, state=state, reason=reason, **fields)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        self.outbox.cancel(unfinished_jobs_of_cases(self.session, [case.case_id]), f"case {case.case_id} is {state.value}: {reason}")
        if state != CaseState.CANCELLED:
            logger.info("Case %s (%s) is %s: %s", case.case_id, context.scenario_name(case), state.value, reason)
        return moved

    # Helpers

    def _save(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, **fields: Any) -> CaseRecord:
        moved = self._move(case, stage=context.graph.stage_of(progress), progress=progress.to_json(), **fields)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        return moved

    def _move(self, case: CaseRecord, **changes: Any) -> CaseRecord:
        try:
            return self.stores.cases.move_case(case.case_id, case.version, session=self.session, **changes)
        except CaseConflict as conflict:
            # Only the engine moves cases, so the case changed earlier in this transaction; retry on its current version
            current = conflict.current
            if current is None or current.state.is_final:
                raise
            return self.stores.cases.move_case(case.case_id, current.version, session=self.session, **changes)

    def _intents(self, context: CampaignContext, case: CaseRecord, due: List[Tuple[Step, Dict[str, Any]]]) -> None:
        """Writes the intents of the due jobs, each checked first; an invalid payload fails the case and writes none."""
        submissions = []
        for step, payload in due:
            key = step.idempotency_key(context.campaign_id, case.case_id)
            try:
                submissions.append((step, key, context.builder.submission(step, payload, key, context.pinned)))
            except PayloadError as error:
                self.end(context, case, CaseState.FAILED, f"the {step.name} payload is invalid: {error}")
                return
        for step, key, submission in submissions:
            self.stores.pipeline.add_intent(
                context.campaign_id, case.case_id, step.stage, key, run_index=step.run_index, repeat_index=step.repeat_index, submission=submission.model_dump(mode="json"), session=self.session
            )
