"""JSON views of campaigns and their classes, cases, jobs, results and events for the operator API.

Plain dictionaries with ISO times (UTC, as stored), in the style of views.py. Enum values
are their wire strings, and a verdict count map is keyed by the run index as a string.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from scenegems_tool.persistence.stores import (
    CampaignEventRecord,
    CampaignRecord,
    CaseRecord,
    ClassCoverage,
    ClassRecord,
    ConfigVersionRecord,
    JobRecord,
    PipelineJobRecord,
    RunRecord,
    VerdictRecord,
)

VERDICT_COLUMNS = (
    "verdict_id",
    "class_id",
    "case_id",
    "run_index",
    "state",
    "monitor",
    "failed_rules",
    "first_failure_time_s",
    "margin",
    "sensitive",
    "early_stop_time_s",
    "created_at",
)


def iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def campaign_view(campaign: CampaignRecord) -> Dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "name": campaign.name,
        "desired_state": campaign.desired_state.value,
        "actual_state": campaign.actual_state.value,
        "state_reason": campaign.state_reason,
        "config_version": campaign.config_version,
        "pinned_fingerprints": campaign.pinned_fingerprints,
        "created_at": iso(campaign.created_at),
        "updated_at": iso(campaign.updated_at),
        "started_at": iso(campaign.started_at),
        "finished_at": iso(campaign.finished_at),
    }


def verdict_counts(coverage: ClassCoverage) -> Dict[str, Dict[str, int]]:
    return {str(run_index): {state.value: count for state, count in states.items()} for run_index, states in coverage.verdicts.items()}


def class_view(record: ClassRecord, coverage: Optional[ClassCoverage] = None) -> Dict[str, Any]:
    return {
        "class_id": record.class_id,
        "state": record.state.value,
        "state_reason": record.state_reason,
        "content_hash": record.content_hash,
        "vessel_count": record.vessel_count,
        "obstacle_count": record.obstacle_count,
        "quota": record.quota,
        "failure_budget": record.failure_budget,
        "failure_budget_left": record.failure_budget_left,
        "complete": record.complete_count,
        "dropped": record.dropped_count,
        "in_flight": record.in_flight_count,
        "verdicts": {} if coverage is None else verdict_counts(coverage),
        "created_at": iso(record.created_at),
        "updated_at": iso(record.updated_at),
        "finished_at": iso(record.finished_at),
    }


def classes_view(records: Sequence[ClassRecord], coverage: Iterable[ClassCoverage]) -> List[Dict[str, Any]]:
    by_class = {entry.class_id: entry for entry in coverage}
    return [class_view(record, by_class.get(record.class_id)) for record in records]


def campaign_detail_view(campaign: CampaignRecord, classes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The campaign with its classes (counts and verdicts per run and state) and their totals."""
    verdicts: Dict[str, int] = {}
    for entry in classes:
        for states in entry["verdicts"].values():
            for state, count in states.items():
                verdicts[state] = verdicts.get(state, 0) + count
    view = campaign_view(campaign)
    view["totals"] = {
        "classes": len(classes),
        "classes_open": sum(1 for entry in classes if entry["state"] == "open"),
        "classes_complete": sum(1 for entry in classes if entry["state"] == "complete"),
        "classes_abandoned": sum(1 for entry in classes if entry["state"] == "abandoned"),
        "quota": sum(entry["quota"] for entry in classes),
        "complete": sum(entry["complete"] for entry in classes),
        "dropped": sum(entry["dropped"] for entry in classes),
        "in_flight": sum(entry["in_flight"] for entry in classes),
        "verdicts": verdicts,
    }
    view["classes"] = classes
    return view


def case_view(case: CaseRecord) -> Dict[str, Any]:
    return {
        "case_id": case.case_id,
        "campaign_id": case.campaign_id,
        "class_id": case.class_id,
        "case_index": case.case_index,
        "seed": case.seed,
        "config_version": case.config_version,
        "stage": case.stage.value,
        "state": case.state.value,
        "scene_artifact": case.scene_artifact,
        "trajectories_artifact": case.trajectories_artifact,
        "trajectories_complete": case.trajectories_complete,
        "reason": case.reason,
        "created_at": iso(case.created_at),
        "updated_at": iso(case.updated_at),
        "finished_at": iso(case.finished_at),
    }


def case_job_view(pipeline_job: PipelineJobRecord, job: Optional[JobRecord]) -> Dict[str, Any]:
    """A case's job: the pipeline link, and the job's state without its payload and result (GET /cluster/jobs/<id> has those)."""
    view: Dict[str, Any] = {
        "stage": pipeline_job.stage.value,
        "run_index": pipeline_job.run_index,
        "repeat_index": pipeline_job.repeat_index,
        "idempotency_key": pipeline_job.idempotency_key,
        "job_id": pipeline_job.job_id,
        "intent": pipeline_job.is_intent,
        "created_at": iso(pipeline_job.created_at),
        "submitted_at": iso(pipeline_job.submitted_at),
        "job": None,
    }
    if job is not None:
        view["job"] = {
            "job_type": job.job_type.value,
            "state": job.state.value,
            "priority": job.priority,
            "attempt": job.attempt,
            "failed_attempts": job.failed_attempts,
            "max_attempts": job.max_attempts,
            "lease_owner": job.lease_owner,
            "available_at": iso(job.available_at),
            "started_at": iso(job.started_at),
            "finished_at": iso(job.finished_at),
            "error": job.error,
        }
    return view


def run_record_view(record: RunRecord) -> Dict[str, Any]:
    return {
        "run_record_id": record.run_record_id,
        "case_id": record.case_id,
        "campaign_id": record.campaign_id,
        "class_id": record.class_id,
        "run_index": record.run_index,
        "repeat_index": record.repeat_index,
        "trajectory_generator": record.trajectory_generator.value,
        "trajectories_complete": record.trajectories_complete,
        "stack": record.stack,
        "repeatability_tier": record.repeatability_tier,
        "environment": record.environment,
        "seed": record.seed,
        "dt": record.dt,
        "steps": record.steps,
        "state_digest": record.state_digest,
        "artifacts": record.artifacts,
        "job_id": record.job_id,
        "node_id": record.node_id,
        "fingerprints": record.fingerprints,
        "durations_s": record.durations_s,
        "created_at": iso(record.created_at),
    }


def verdict_view(verdict: VerdictRecord) -> Dict[str, Any]:
    return {
        "verdict_id": verdict.verdict_id,
        "case_id": verdict.case_id,
        "campaign_id": verdict.campaign_id,
        "class_id": verdict.class_id,
        "run_index": verdict.run_index,
        "run_record_id": verdict.run_record_id,
        "state": verdict.state.value,
        "monitor": verdict.monitor.value,
        "rule_outcomes": verdict.rule_outcomes,
        "failed_rules": list(verdict.failed_rules),
        "first_failure_time_s": verdict.first_failure_time_s,
        "margin": verdict.margin,
        "sensitive": verdict.sensitive,
        "early_stop_time_s": verdict.early_stop_time_s,
        "created_at": iso(verdict.created_at),
    }


def verdict_row(verdict: VerdictRecord) -> List[Any]:
    """The verdict as a CSV row in VERDICT_COLUMNS order: failed rules joined with a semicolon, empty cells for nulls."""
    values = verdict_view(verdict)
    values["failed_rules"] = ";".join(verdict.failed_rules)
    return ["" if values[column] is None else values[column] for column in VERDICT_COLUMNS]


def event_view(event: CampaignEventRecord) -> Dict[str, Any]:
    return {"event_id": event.event_id, "at": iso(event.at), "kind": event.kind.value, "class_id": event.class_id, "detail": event.detail}


def config_version_view(version: ConfigVersionRecord) -> Dict[str, Any]:
    return {"version": version.version, "config_hash": version.config_hash, "created_at": iso(version.created_at), "config": version.config}
