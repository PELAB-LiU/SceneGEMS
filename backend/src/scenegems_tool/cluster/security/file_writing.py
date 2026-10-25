"""Atomic writes for the master's security folder.

Every file is written next to its target and then renamed over it, so a reader never
sees half a file. Secret files are created readable by their owner only (POSIX modes;
on Windows the folder's access rules apply).
"""

import os
from pathlib import Path


def write_private_file(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)
    os.replace(temporary, path)


def write_public_file(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
