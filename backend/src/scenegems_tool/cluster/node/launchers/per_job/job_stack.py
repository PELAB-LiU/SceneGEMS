"""A per-job stack: one compose project per job, run to completion and removed.

The stack holds a runner service, which executes the job in a subsystem image, and the
services the job needs next to it (SITL, Gazebo). Names come from the job's instance scope
and published ports are dropped, so any number of stacks run side by side on one host.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Dict, List, Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.node.launchers.docker_cli import copy_from_container, copy_into_container
from scenegems_tool.cluster.node.launchers.per_job.job_container_io import (
    JOB_CONTAINER_MAIN,
    JOB_DOCUMENT,
    JOB_FOLDER,
    RESULT_DOCUMENT,
    parse_status_line,
)
from scenegems_tool.cluster.protocol.messages import LogStream

RUNNER_SERVICE = "runner"
_WAIT_POLL_S = 0.2
_LOG_DRAIN_TIMEOUT_S = 5.0


def runner_service(image: str, *, networks: Optional[List[str]] = None, depends_on: Optional[List[str]] = None, cpus: Optional[float] = None) -> dict:
    """The service that runs the job's in-container part; without networks it has no network at all."""
    service: dict = {
        "image": image,
        "command": ["python", "-m", JOB_CONTAINER_MAIN],
        "environment": {"PYTHONUNBUFFERED": "1"},
    }
    if cpus is not None:
        service["cpus"] = cpus
    if depends_on:
        service["depends_on"] = list(depends_on)
    if networks:
        service["networks"] = list(networks)
    else:
        service["network_mode"] = "none"
    return service


def scope_services(scope: InstanceScope, services: Dict[str, dict]) -> Dict[str, dict]:
    """Container names from the scope; published ports dropped, since instances share the host."""
    scoped = {}
    for key, service in services.items():
        service = dict(service)
        service["container_name"] = scope.container_name(key)
        service.pop("ports", None)
        service.pop("restart", None)  # a job's containers stop with the job
        scoped[key] = service
    return scoped


class JobStack:
    def __init__(self, scope: InstanceScope, services: Dict[str, dict], *, networks: Optional[dict] = None, volumes: Optional[dict] = None):
        if RUNNER_SERVICE not in services:
            raise ValueError(f"A job stack needs a {RUNNER_SERVICE!r} service")
        self.scope = scope
        self.compose: dict = {"services": scope_services(scope, services)}
        if networks:
            self.compose["networks"] = networks
        if volumes:
            self.compose["volumes"] = volumes
        self.runner_container = scope.container_name(RUNNER_SERVICE)
        self.project = ComposeProject(scope.compose_project, f"{scope.folder}/docker-compose.yml")

    def run(self, job_document: dict, report: JobReport, *, timeout_s: float, cancel: Optional[threading.Event] = None) -> JobResultData:
        """Create the stack, hand the runner its job, wait for it to stop and return its result. The stack is removed either way."""
        try:
            self.project.force_remove(networks=True)  # a leftover of an earlier run of this scope
            self.project.write(self.compose)
            report.status("creating the job stack")
            self.project.create()
            self._copy_job_document(job_document)
            self.project.start()
            report.status("running")
            followers = _follow_logs(self.runner_container, report)
            exit_code = self._wait(timeout_s, cancel)
            for follower in followers:
                follower.join(timeout=_LOG_DRAIN_TIMEOUT_S)
            outcome = self._read_outcome()
        except subprocess.CalledProcessError as error:
            raise JobFailed(f"Docker failed for job stack {self.project.name}: {error.stderr or error}", retryable=True) from error
        finally:
            self.project.force_remove(networks=True)
            shutil.rmtree(self.scope.folder, ignore_errors=True)
        if exit_code != 0 or "result" not in outcome:
            reason = outcome.get("error") or f"the runner exited with code {exit_code} and no result"
            raise JobFailed(str(reason), retryable=bool(outcome.get("retryable", False)))
        return outcome["result"]

    def _copy_job_document(self, job_document: dict) -> None:
        with tempfile.TemporaryDirectory(prefix="scenegems-job-") as folder:
            with open(os.path.join(folder, JOB_DOCUMENT), "w", encoding="utf-8") as file:
                json.dump(job_document, file)
            # "<folder>/." copies the folder's content and creates JOB_FOLDER in the container.
            copy_into_container(os.path.join(folder, "."), self.runner_container, JOB_FOLDER)

    def _wait(self, timeout_s: float, cancel: Optional[threading.Event]) -> int:
        process = subprocess.Popen(["docker", "wait", self.runner_container], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                output, _ = process.communicate(timeout=_WAIT_POLL_S)
                return int(output.strip().splitlines()[-1])
            except subprocess.TimeoutExpired:
                pass
            except (ValueError, IndexError) as error:
                raise JobFailed(f"Could not read the exit code of {self.runner_container}", retryable=True) from error
            if cancel is not None and cancel.is_set():
                process.kill()
                raise JobFailed("cancelled", retryable=False)
            if time.monotonic() > deadline:
                process.kill()
                raise JobFailed(f"timed out after {timeout_s:g} s", retryable=True)

    def _read_outcome(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="scenegems-result-") as folder:
            local = os.path.join(folder, RESULT_DOCUMENT)
            if not copy_from_container(self.runner_container, f"{JOB_FOLDER}/{RESULT_DOCUMENT}", local):
                return {}
            with open(local, encoding="utf-8") as file:
                return json.load(file)


def _follow_logs(container: str, report: JobReport) -> List[threading.Thread]:
    """Forward the container's output to the report until it stops: status lines as status, the rest as log lines."""
    process = subprocess.Popen(["docker", "logs", "-f", container], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")

    def forward(pipe, stream: LogStream) -> None:
        for line in pipe:
            line = line.rstrip("\r\n")
            status = parse_status_line(line) if stream == LogStream.STDOUT else None
            if status is not None:
                report.status(*status)
            elif line:
                report.log(container, line, stream)

    followers = [
        threading.Thread(target=forward, args=(process.stdout, LogStream.STDOUT), name=f"{container}_stdout", daemon=True),
        threading.Thread(target=forward, args=(process.stderr, LogStream.STDERR), name=f"{container}_stderr", daemon=True),
    ]
    for follower in followers:
        follower.start()
    return followers
