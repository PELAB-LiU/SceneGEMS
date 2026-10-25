from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

from scenegems_tool.cluster.master.api.master_apps import create_master_apps, create_operator_app
from scenegems_tool.cluster.master.api.operator_routes import STATUS_PATH
from scenegems_tool.cluster.protocol.routes import CA_CERTIFICATE_PATH, JOBS_PATH, NODE_CONTROL_PATH, PAIRING_PATH
from scenegems_tool.cluster.security.broker.auth_hook import AUTH_HOOK_PATH
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, MASTER_PASSWORD, MASTER_USERNAME


def _stub_gateway(events):
    @asynccontextmanager
    async def lifespan(_app):
        events.append("gateway up")
        yield
        events.append("gateway down")

    gateway = FastAPI(lifespan=lifespan)

    @gateway.get("/health")
    def health():
        return {"status": "ok"}

    @gateway.get(STATUS_PATH)
    def shadowed():
        return {"from": "gateway"}

    @gateway.websocket("/ws/scenegems_backend_service")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hello from the workbench")
        await websocket.close()

    return gateway


def _paths(app: FastAPI):
    return {getattr(route, "path", None) for route in app.routes}


def test_each_listener_serves_only_its_routes(plane, security):
    apps = create_master_apps(plane, security, HOOK_SECRET)
    assert {CA_CERTIFICATE_PATH, PAIRING_PATH, NODE_CONTROL_PATH} <= _paths(apps.node_api)
    assert not {JOBS_PATH, "/ws/scenegems_backend_service"} & _paths(apps.node_api)
    assert JOBS_PATH in _paths(apps.operator) and not {PAIRING_PATH, NODE_CONTROL_PATH} & _paths(apps.operator)
    assert AUTH_HOOK_PATH in _paths(apps.broker_hook)


def test_the_gateway_is_mounted_behind_the_operator_routes_with_its_lifespan(plane):
    events = []
    with TestClient(create_operator_app(plane, _stub_gateway(events))) as client:
        assert events == ["gateway up"]
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get(STATUS_PATH).json()["master_id"] == "lab-master"  # the cluster route wins
        with client.websocket_connect("/ws/scenegems_backend_service") as socket:
            assert socket.receive_text() == "hello from the workbench"
    assert events == ["gateway up", "gateway down"]


def test_the_real_workbench_gateway_mounts_unchanged(plane):
    from scenegems_tool.gateway.websocket_app import app as gateway

    operator = create_operator_app(plane, gateway)
    client = TestClient(operator)  # no lifespan: the gateway's would install signal handlers and stop Docker containers at exit
    assert client.get("/health").json() == {"status": "ok"}
    mounted = next(route for route in operator.routes if getattr(route, "app", None) is gateway)
    assert "/ws/scenegems_backend_service" in _paths(mounted.app)


def test_the_broker_hook_checks_logins(plane, security):
    hook = TestClient(create_master_apps(plane, security, HOOK_SECRET).broker_hook)
    headers = {"Authorization": f"Bearer {HOOK_SECRET}"}
    assert hook.post(AUTH_HOOK_PATH, data={"username": MASTER_USERNAME, "password": MASTER_PASSWORD}, headers=headers).status_code == 200
    assert hook.post(AUTH_HOOK_PATH, data={"username": MASTER_USERNAME, "password": "wrong-password-123"}, headers=headers).status_code == 401
    assert hook.post(AUTH_HOOK_PATH, data={"username": MASTER_USERNAME, "password": MASTER_PASSWORD}).status_code == 401
