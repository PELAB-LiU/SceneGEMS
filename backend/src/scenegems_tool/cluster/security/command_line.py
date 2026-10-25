"""Command line of the master's security: `python -m scenegems_tool.cluster.security`.

    init                     create or update the security folder (CA, certificates, broker files)
    pairing-token create     print a new one-time pairing token
    pairing-token purge      remove expired tokens
    node revoke <node_id>    remove a node's credential and broker account

Settings come from the environment, usually loaded with `--env-file deploy/master/.env`.
Passwords are read only from there, never from arguments, which other users of the
machine could see in the process list. Only `pairing-token create` prints a secret: the
token, alone on stdout, so a script can capture it.
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

from scenegems_tool.cluster.security.broker.broker_config import TLS_PORT, ClusterBrokerSettings
from scenegems_tool.cluster.security.certificates.subject_names import split_address_list
from scenegems_tool.cluster.security.credentials.broker_accounts import remove_broker_account
from scenegems_tool.cluster.security.credentials.node_credentials import revoke_node_credential
from scenegems_tool.cluster.security.credentials.pairing_tokens import DEFAULT_TOKEN_LIFETIME, create_pairing_token, purge_expired_pairing_tokens
from scenegems_tool.cluster.security.master_security import MasterSecurity, initialize_master_security

_DURATION_PATTERN = re.compile(r"^(\d+)([smhd])$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


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


def _run_pairing_token(arguments: argparse.Namespace, environ: Mapping[str, str]) -> int:
    security = MasterSecurity.load(_security_dir(arguments, environ))
    if arguments.token_command == "create":
        created = create_pairing_token(security.store, lifetime=arguments.lifetime, note=arguments.note)
        print(created.token)
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
    create = token_commands.add_parser("create", help="print a new token")
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
