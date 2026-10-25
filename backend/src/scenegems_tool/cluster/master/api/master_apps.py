"""The master's three FastAPI apps, one per listener, because each listener has its own audience.

All three run in the master process on one event loop (server.py) and share one control plane.

    node API     HTTPS with the master's certificate, reachable by nodes on the network:
                 CA certificate, pairing, control WebSocket (node_routes.py), artifact
                 downloads and uploads (artifact_routes.py). Its lifespan runs the control
                 plane and the artifact sweep.
    operator     plain HTTP bound to the local machine: the workbench WebSocket gateway,
                 mounted unchanged with its own lifespan, the job and node routes
                 (operator_routes.py, and campaign_routes.py with the campaign stores) and
                 artifact reads. Neither has authentication yet, which is why they are
                 not on the node API's listener.
    broker hook  plain HTTP on the compose network only: the cluster broker's login check
                 (cluster/security/broker/auth_hook.py).
"""

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI

from scenegems_tool.cluster.master.api.artifact_routes import lease_holder_of, node_artifact_router, operator_artifact_router
from scenegems_tool.cluster.master.api.node_routes import node_router
from scenegems_tool.cluster.master.api.operator_routes import operator_router
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.master_artifacts import MasterArtifacts
from scenegems_tool.cluster.security.broker.auth_hook import create_broker_auth_app
from scenegems_tool.cluster.security.master_security import MasterSecurity
from scenegems_tool.persistence.stores import AssuranceStores


@dataclass(frozen=True)
class MasterApps:
    node_api: FastAPI
    operator: FastAPI
    broker_hook: FastAPI


def create_node_api_app(plane: ControlPlane, security: MasterSecurity, run_timers: bool = True, artifacts: Optional[MasterArtifacts] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await plane.start(timers=run_timers)
        if artifacts is not None and run_timers:
            artifacts.start_sweep()
        try:
            yield
        finally:
            if artifacts is not None:
                await artifacts.stop_sweep()
            await plane.stop()

    app = FastAPI(title=f"SceneGEMS master {plane.master_id}: node API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(node_router(plane, security))
    if artifacts is not None:
        app.include_router(node_artifact_router(artifacts.artifacts, security, lease_holder_of(plane.jobs), artifacts.max_bytes))
    return app


def create_operator_app(plane: ControlPlane, gateway: Optional[FastAPI] = None, artifacts: Optional[MasterArtifacts] = None, assurance: Optional[AssuranceStores] = None) -> FastAPI:
    """The operator routes, with the workbench gateway mounted behind them when given.

    The campaign routes need the campaign stores (assurance); without them they answer 503.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with AsyncExitStack() as stack:
            if gateway is not None:
                await stack.enter_async_context(gateway.router.lifespan_context(gateway))
            yield

    app = FastAPI(title=f"SceneGEMS master {plane.master_id}: operator API", lifespan=lifespan)
    app.include_router(operator_router(plane, assurance))
    if artifacts is not None:
        app.include_router(operator_artifact_router(artifacts.artifacts))
    if gateway is not None:
        app.mount("/", gateway)  # last, so the cluster routes match first
    return app


def create_master_apps(
    plane: ControlPlane,
    security: MasterSecurity,
    broker_hook_secret: str,
    gateway: Optional[FastAPI] = None,
    run_timers: bool = True,
    artifacts: Optional[MasterArtifacts] = None,
    assurance: Optional[AssuranceStores] = None,
) -> MasterApps:
    return MasterApps(
        node_api=create_node_api_app(plane, security, run_timers, artifacts),
        operator=create_operator_app(plane, gateway, artifacts, assurance),
        broker_hook=create_broker_auth_app(security.store, broker_hook_secret),
    )
