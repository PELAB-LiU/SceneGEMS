"""How a per-job runner container receives its job and hands back its result.

The launcher copies the job document into the created container before it starts and
copies the result document out after it stops, so the caller needs only the Docker CLI,
not a volume shared with the container. While it runs, the container writes status lines
to stdout with STATUS_LINE_PREFIX; every other line is a log line.
"""

import json
from typing import Optional, Tuple

JOB_FOLDER = "/job"
JOB_DOCUMENT = "job.json"  # {"job": JobSpec}
RESULT_DOCUMENT = "result.json"  # {"result": {...}} or {"error": "...", "retryable": bool}
JOB_CONTAINER_MAIN = "scenegems_tool.cluster.node.jobs.in_container.job_container_main"
STATUS_LINE_PREFIX = "scenegems-status "


def format_status_line(message: str, progress: Optional[float] = None) -> str:
    return STATUS_LINE_PREFIX + json.dumps({"message": message, "progress": progress})


def parse_status_line(line: str) -> Optional[Tuple[str, Optional[float]]]:
    """(message, progress) of a status line, None for a log line."""
    if not line.startswith(STATUS_LINE_PREFIX):
        return None
    try:
        status = json.loads(line[len(STATUS_LINE_PREFIX) :])
        return str(status["message"]), status.get("progress")
    except (ValueError, KeyError, TypeError):
        return None
