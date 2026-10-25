"""Command line of the master's security: `python -m scenegems_tool.cluster.security`.

    init                     create or update the security folder (CA, certificates, broker files)
    pairing-token create     print a new one-time pairing token with what a node's .env needs
    pairing-token purge      remove expired tokens
    node revoke <node_id>    remove a node's credential and broker account

Settings come from the environment, usually loaded with `--env-file deploy/master/.env`.
Passwords are read only from there, never from arguments, which other users of the
machine could see in the process list. Only `pairing-token create` prints a secret. It
prints the lines of a node's .env on stdout (master id, master URL, token and CA
certificate hash, design doc 13.9), so a script can append them; --token-only prints the
token alone.
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

from scenegems_tool.cluster.security.broker.broker_config import TLS_PORT, ClusterBrokerSettings
from scenegems_tool.cluster.security.certificates.certificate_pinning import certificate_sha256
from scenegems_tool.cluster.security.certificates.subject_names import split_address_list
from scenegems_tool.cluster.security.credentials.broker_accounts import remove_broker_account
from scenegems_tool.cluster.security.credentials.node_credentials import revoke_node_credential
from scenegems_tool.cluster.security.credentials.pairing_tokens import DEFAULT_TOKEN_LIFETIME, create_pairing_token, purge_expired_pairing_tokens
from scenegems_tool.cluster.security.master_security import MasterSecurity, initialize_master_security

_DURATION_PATTERN = re.compile(r"^(\d+)([smhd])$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
DEFAULT_API_PORT = 8443
# The lines of a node's .env that pairing needs (deploy/node/.env.example)
MASTER_ID_VARIABLE = "SCENEGEMS_MASTER_ID"
MASTER_URL_VARIABLE = "SCENEGEMS_MASTER_URL"
PAIRING_TOKEN_VARIABLE = "SCENEGEMS_PAIRING_TOKEN"
MASTER_CA_SHA256_VARIABLE = "SCENEGEMS_MASTER_CA_SHA256"


class CommandLineError(Exception):
    pass


def parse_duration(text: str) -> datetime.timedelta:
    match = _DURATION_PATTERN.fullmatch(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid duration {text!r}; use a number with s, m, h or d, for example 30m")
    return datetime.timedelta(**{_DURATION_UNITS[match.group(2)]: int(match.group(1))})


def load_env_file(path: Path, environ: dict) -> None:
    """KEY=VALUE lines into `environ`; variables already set keep their value."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        environ.setdefault(key, value)


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise CommandLineError(f"{name} is not set; set it in deploy/master/.env (see .env.example)")
    return value


def _security_dir(arguments: argparse.Namespace, environ: Mapping[str, str]) -> Path:
    if arguments.security_dir:
        return Path(arguments.security_dir)
    folder = Path(_required(environ, "SCENEGEMS_SECURITY_DIR"))
    # Compose resolves a relative folder against deploy/master, where the .env file lives.
    if not folder.is_absolute() and arguments.env_file:
        folder = Path(arguments.env_file).resolve().parent / folder
    return folder


def _run_init(arguments: argparse.Namespace, environ: Mapping[str, str]) -> int:
    addresses = arguments.address or split_address_list(environ.get("SCENEGEMS_MASTER_ADDRESSES", ""))
    security = initialize_master_security(
        _security_dir(arguments, environ),
        master_id=arguments.master_id or _required(environ, "SCENEGEMS_MASTER_ID"),
        addresses=addresses,
        master_broker_username=environ.get("SCENEGEMS_BROKER_MASTER_USERNAME", "").strip() or "master",
        master_broker_password=_required(environ, "SCENEGEMS_BROKER_MASTER_PASSWORD"),
        broker=ClusterBrokerSettings(
            auth_hook_url=_required(environ, "SCENEGEMS_BROKER_AUTH_HOOK_URL"),
            auth_hook_secret=_required(environ, "SCENEGEMS_BROKER_AUTH_HOOK_SECRET"),
        ),
        broker_public_host=environ.get("SCENEGEMS_BROKER_PUBLIC_HOST", "").strip() or None,
        broker_public_port=int(environ.get("SCENEGEMS_BROKER_TLS_PORT", "").strip() or TLS_PORT),
    )
    print(f"Master {security.master_id}: security folder ready at {security.layout.root}")
    print(f"Certificates valid for: {', '.join(security.identity.addresses)} and the local defaults")
    print(f"Nodes reach the broker at {security.identity.broker_public_host}:{security.identity.broker_public_port}")
    return 0


def master_url(security: MasterSecurity, environ: Mapping[str, str]) -> str:
    """The URL nodes use for the master API: SCENEGEMS_MASTER_URL, else the first master address with SCENEGEMS_API_PORT."""
    configured = environ.get(MASTER_URL_VARIABLE, "").strip()
    if configured:
        return configured.rstrip("/")
    host = security.identity.addresses[0]
    if ":" in host:  # an IPv6 address
        host = f"[{host}]"
    port = int(environ.get("SCENEGEMS_API_PORT", "").strip() or DEFAULT_API_PORT)
    return f"https://{host}:{port}"


def _run_pairing_token(arguments: argparse.Namespace, environ: Mapping[str, str]) -> int:
    security = MasterSecurity.load(_security_dir(arguments, environ))
    if arguments.token_command == "create":
        created = create_pairing_token(security.store, lifetime=arguments.lifetime, note=arguments.note)
        if arguments.token_only:
            print(created.token)
        else:
            print(f"{MASTER_ID_VARIABLE}={security.master_id}")
            print(f"{MASTER_URL_VARIABLE}={master_url(security, environ)}")
            print(f"{PAIRING_TOKEN_VARIABLE}={created.token}")
            print(f"{MASTER_CA_SHA256_VARIABLE}={certificate_sha256(security.ca_certificate_pem)}")
        print(f"Pairing token for master {security.master_id}, valid once until {created.expires_at.isoformat(timespec='seconds')}", file=sys.stderr)
        return 0
    removed = purge_expired_pairing_tokens(security.store)
    print(f"Removed {removed} expired pairing token(s)")
    return 0


def _run_node(arguments: argparse.Namespace, environ: Mapping[str, str]) -> int:
    security = MasterSecurity.load(_security_dir(arguments, environ))
    removed_credential = revoke_node_credential(security.store, arguments.node_id)
    removed_account = remove_broker_account(security.store, arguments.node_id)
    if not (removed_credential or removed_account):
        print(f"No node {arguments.node_id!r} is paired with master {security.master_id}", file=sys.stderr)
        return 1
    print(f"Node {arguments.node_id} revoked; its open broker connection lasts until it reconnects")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scenegems_tool.cluster.security", description="Security of a SceneGEMS master.")
    parser.add_argument("--env-file", type=Path, help="read settings from this .env file (variables already set win)")
    parser.add_argument("--security-dir", help="the master's security folder (default SCENEGEMS_SECURITY_DIR)")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create or update the security folder")
    init.add_argument("--master-id", help="default SCENEGEMS_MASTER_ID")
    init.add_argument("--address", action="append", help="an IP address or host name of the master; repeat for more (default SCENEGEMS_MASTER_ADDRESSES)")

    tokens = commands.add_parser("pairing-token", help="one-time pairing tokens")
    token_commands = tokens.add_subparsers(dest="token_command", required=True)
    create = token_commands.add_parser("create", help="print a new token, the master URL and the CA certificate hash as .env lines")
    create.add_argument("--token-only", action="store_true", help="print the token alone")
    create.add_argument("--lifetime", type=parse_duration, default=DEFAULT_TOKEN_LIFETIME, help="for example 30m, 2h or 1d (default 30m)")
    create.add_argument("--note", default="", help="a reminder stored with the token, for example the node's name")
    token_commands.add_parser("purge", help="remove expired tokens")

    node = commands.add_parser("node", help="paired nodes")
    node_commands = node.add_subparsers(dest="node_command", required=True)
    revoke = node_commands.add_parser("revoke", help="remove a node's credential and broker account")
    revoke.add_argument("node_id")
    return parser


def main(argv: Optional[Sequence[str]] = None, environ: Optional[dict] = None) -> int:
    arguments = build_parser().parse_args(argv)
    environ = dict(os.environ) if environ is None else environ
    try:
        if arguments.env_file:
            load_env_file(arguments.env_file, environ)
        if arguments.command == "init":
            return _run_init(arguments, environ)
        if arguments.command == "pairing-token":
            return _run_pairing_token(arguments, environ)
        return _run_node(arguments, environ)
    except (CommandLineError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
