"""The master's settings, from the environment (deploy/master/.env through compose, or --env-file).

The compose service sets the listeners and folders itself; the secrets come from the .env file.

    SCENEGEMS_SECURITY_DIR            security folder from `cluster.security init` (required)
    SCENEGEMS_DATABASE_URL            Postgres of the job store and node registry (required)
    SCENEGEMS_BROKER_AUTH_HOOK_SECRET the secret the cluster broker sends with each login check (required)
    SCENEGEMS_API_LISTEN_HOST, _PORT          node API, HTTPS (default 0.0.0.0:8443)
    SCENEGEMS_OPERATOR_LISTEN_HOST, _PORT     workbench gateway and operator API (default 127.0.0.1:5174)
    SCENEGEMS_BROKER_HOOK_LISTEN_HOST, _PORT  broker login hook (default 127.0.0.1:8090)
    SCENEGEMS_FINGERPRINT_REPO_ROOT   the checkout whose image fingerprints the master requires
                                      (default: the checkout this code runs from)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from scenegems_tool.persistence.database import DATABASE_URL_ENV


class SettingMissing(ValueError):
    pass


@dataclass(frozen=True)
class Listener:
    host: str
    port: int


@dataclass(frozen=True)
class MasterSettings:
    security_dir: Path
    database_url: str = field(repr=False)
    broker_hook_secret: str = field(repr=False)
    node_api: Listener = Listener("0.0.0.0", 8443)
    operator: Listener = Listener("127.0.0.1", 5174)
    broker_hook: Listener = Listener("127.0.0.1", 8090)
    fingerprint_repo_root: Optional[Path] = None

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None, env_file_folder: Optional[Path] = None) -> "MasterSettings":
        """Reads the settings; a relative security folder is relative to env_file_folder (as compose resolves it)."""
        environ = os.environ if environ is None else environ
        security_dir = Path(_required(environ, "SCENEGEMS_SECURITY_DIR"))
        if not security_dir.is_absolute() and env_file_folder is not None:
            security_dir = env_file_folder / security_dir
        repo_root = environ.get("SCENEGEMS_FINGERPRINT_REPO_ROOT", "").strip()
        return cls(
            security_dir=security_dir,
            database_url=_required(environ, DATABASE_URL_ENV),
            broker_hook_secret=_required(environ, "SCENEGEMS_BROKER_AUTH_HOOK_SECRET"),
            node_api=_listener(environ, "SCENEGEMS_API", cls.node_api),
            operator=_listener(environ, "SCENEGEMS_OPERATOR", cls.operator),
            broker_hook=_listener(environ, "SCENEGEMS_BROKER_HOOK", cls.broker_hook),
            fingerprint_repo_root=Path(repo_root) if repo_root else None,
        )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SettingMissing(f"{name} is not set; see deploy/master/.env.example")
    return value


def _listener(environ: Mapping[str, str], prefix: str, default: Listener) -> Listener:
    host = environ.get(f"{prefix}_LISTEN_HOST", "").strip() or default.host
    port = environ.get(f"{prefix}_LISTEN_PORT", "").strip()
    return Listener(host, int(port) if port else default.port)
