"""The node's entry point for a leased job: run_job(job, node, report).

The daemon (P3.4) calls it on a worker thread per lease, within the node's slots. It
returns the job's result or raises JobFailed; any other exception is a failure that may
succeed on another attempt.
"""

import threading
from typing import Optional

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_types import job_type_module
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.protocol.jobs import JobSpec


def run_job(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    """Run one job in its subsystem container and return its result. Setting cancel stops it."""
    if node.slots and job.job_type not in node.slots:
        raise JobFailed(f"This node offers no {job.job_type.value} slots", retryable=True)
    return job_type_module(job.job_type).run(job, node, report, cancel)
