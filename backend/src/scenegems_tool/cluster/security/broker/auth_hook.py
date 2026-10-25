"""The endpoint NanoMQ calls to check a login (NanoMQ `auth.http_auth.auth_req`).

NanoMQ posts the client's username and password as a form and accepts the login on
HTTP 200 only. The request must carry the shared hook secret, so nobody else can use the
endpoint to guess passwords. The endpoint belongs on a port only the broker reaches;
P3.3 mounts `broker_auth_router` there, or runs `create_broker_auth_app` on its own.
"""

import hmac
from urllib.parse import parse_qsl

from fastapi import APIRouter, FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

from scenegems_tool.cluster.security.credentials.broker_accounts import verify_broker_login
from scenegems_tool.cluster.security.store.security_store import SecurityStore

AUTH_HOOK_PATH = "/cluster/broker/auth"
_MAX_FORM_BYTES = 4096


def _has_hook_secret(request: Request, hook_secret: str) -> bool:
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(presented.encode("utf-8"), hook_secret.encode("utf-8"))


def broker_auth_router(store: SecurityStore, hook_secret: str, *, path: str = AUTH_HOOK_PATH) -> APIRouter:
    router = APIRouter()

    @router.post(path, include_in_schema=False)
    async def check_broker_login(request: Request) -> Response:
        if not _has_hook_secret(request, hook_secret):
            return Response(status_code=401)
        body = await request.body()
        if len(body) > _MAX_FORM_BYTES:
            return Response(status_code=413)
        form = dict(parse_qsl(body.decode("utf-8", errors="replace")))
        # scrypt takes tens of milliseconds; keep it off the event loop.
        allowed = await run_in_threadpool(verify_broker_login, store, form.get("username", ""), form.get("password", ""))
        return Response(status_code=200 if allowed else 401)

    return router


def create_broker_auth_app(store: SecurityStore, hook_secret: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(broker_auth_router(store, hook_secret))
    return app
