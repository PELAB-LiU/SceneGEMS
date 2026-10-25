"""Entry point of a per-job runner container: run the job's in-container part and write its result.

The launcher has copied the job document into JOB_FOLDER before the start, and copies the
result document out after the stop (launchers/per_job/job_container_io.py).
"""

import json
import math
import sys
import traceback
from enum import Enum
from typing import Any, Optional

import numpy as np

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs.job_types import job_type_module
from scenegems_tool.cluster.node.launchers.per_job.job_container_io import JOB_DOCUMENT, JOB_FOLDER, RESULT_DOCUMENT, format_status_line
from scenegems_tool.cluster.protocol.jobs import JobSpec


def json_safe(value: Any) -> Any:
    """Plain JSON values: numpy values become numbers and lists, tuples lists, enums their values, non-finite floats None."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def status(message: str, progress: Optional[float] = None) -> None:
    print(format_status_line(message, progress), flush=True)


def _write_outcome(outcome: dict) -> None:
    with open(f"{JOB_FOLDER}/{RESULT_DOCUMENT}", "w", encoding="utf-8") as file:
        json.dump(outcome, file)


def main() -> int:
    with open(f"{JOB_FOLDER}/{JOB_DOCUMENT}", encoding="utf-8") as file:
        job = JobSpec.model_validate(json.load(file)["job"])
    status(f"{job.job_type.value} job {job.job_id} attempt {job.attempt} started")
    try:
        result = job_type_module(job.job_type).execute(job, status)
    except JobFailed as error:
        _write_outcome({"error": str(error), "retryable": error.retryable})
        return 1
    except Exception as error:
        traceback.print_exc()
        _write_outcome({"error": f"{type(error).__name__}: {error}", "retryable": False})
        return 1
    _write_outcome({"result": json_safe(result)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
