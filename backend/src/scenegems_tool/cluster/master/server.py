"""The master process: its three listeners in one event loop (api/master_apps.py says why three).

    python -m scenegems_tool.cluster.master [--env-file deploy/master/.env]

The database must be migrated first (`python -m scenegems_tool.persistence.migrate upgrade
head`; the compose service does both) and the security folder initialized
(`python -m scenegems_tool.cluster.security init`).
"""

import argparse
import asyncio
import contextlib
import logging
import multiprocessing
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional, Sequence

import uvicorn
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.cluster.master.api.master_apps import MasterApps, create_master_apps
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.master.settings import MasterSettings, SettingMissing
from scenegems_tool.cluster.security.command_line import load_env_file
from scenegems_tool.cluster.security.master_security import MasterSecurity
from scenegems_tool.cluster.security.security_layout import SecurityLayout
from scenegems_tool.persistence.database import create_database_engine, create_session_factory
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NodeStore

logger = logging.getLogger(__name__)

STARTUP_POLL_S = 0.1
MAX_NODE_FRAME_BYTES = 64 * 1024 * 1024  # the node daemon's limit; job results can exceed uvicorn's default of 16 MiB


class _Listener(uvicorn.Server):
    """A uvicorn server that leaves signals to the process, which stops every listener at once."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def build_master(settings: MasterSettings, with_gateway: bool = True) -> MasterApps:
    security = MasterSecurity.load(settings.security_dir)
    sessions = create_session_factory(create_database_engine(settings.database_url))
    plane = ControlPlane(security.master_id, NodeStore(sessions), JobStore(sessions), ExpectedFingerprints.of_release(settings.release_manifest))
    attach_campaigns(plane, sessions)
    gateway = None
    if with_gateway:
        from scenegems_tool.gateway.websocket_app import app as gateway

    return create_master_apps(plane, security, settings.broker_hook_secret, gateway=gateway)


def attach_campaigns(plane: ControlPlane, sessions: sessionmaker[Session]) -> AssuranceStores:
    """The master's one AssuranceStores, and the pipeline engine on it as a timer of the control plane.

    Everything that works on campaigns (the engine, the campaign routes, the artifact sweep)
    takes this instance.
    """
    stores = AssuranceStores.create(sessions)
    plane.attach_pipeline(stores)
    return stores


def listeners(settings: MasterSettings, apps: MasterApps) -> List[uvicorn.Server]:
    layout = SecurityLayout(settings.security_dir)
    # uvicorn's loggers are process-wide, so all three listeners share one log setup. Access logs
    # are off: the health check and every broker login would fill them; the master logs its own events.
    logging_options = dict(log_level="info", access_log=False)
    return [
        _Listener(
            uvicorn.Config(
                apps.node_api,
                host=settings.node_api.host,
                port=settings.node_api.port,
                ssl_certfile=str(layout.api_certificate),
                ssl_keyfile=str(layout.api_key),
                ws_max_size=MAX_NODE_FRAME_BYTES,
                **logging_options,
            )
        ),
        # The workbench frontend expects no WebSocket pings, as the gateway's own main runs it
        _Listener(uvicorn.Config(apps.operator, host=settings.operator.host, port=settings.operator.port, ws_ping_interval=None, **logging_options)),
        _Listener(uvicorn.Config(apps.broker_hook, host=settings.broker_hook.host, port=settings.broker_hook.port, **logging_options)),
    ]


async def serve(servers: Sequence[uvicorn.Server]) -> None:
    def stop(*_arguments) -> None:
        for server in servers:
            server.should_exit = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    while not all(server.started for server in servers) and not any(task.done() for task in tasks):
        await asyncio.sleep(STARTUP_POLL_S)
    # Again after startup: the workbench gateway's lifespan installs handlers that end the process at
    # once. These stop every listener instead, and the gateway's lifespan teardown removes its containers.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    await asyncio.gather(*tasks)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenegems_tool.cluster.master", description="Run a SceneGEMS master: node API, operator API with the workbench, broker login hook.")
    parser.add_argument("--env-file", type=Path, help="read settings from this .env file (variables already set win)")
    parser.add_argument("--no-workbench", action="store_true", help="do not mount the workbench gateway on the operator listener")
    arguments = parser.parse_args(argv)
    # force: an import may already have logged, which gives the root logger a WARNING handler
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s", force=True)
    environ = dict(os.environ)
    try:
        if arguments.env_file:
            load_env_file(arguments.env_file, environ)
        settings = MasterSettings.from_environment(environ, env_file_folder=arguments.env_file.resolve().parent if arguments.env_file else None)
        apps = build_master(settings, with_gateway=not arguments.no_workbench)
    except (SettingMissing, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    multiprocessing.set_start_method("spawn", force=True)  # as the gateway's own main: workbench workers are spawned
    asyncio.run(serve(listeners(settings, apps)))
    return 0
