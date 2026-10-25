"""Snapshot comparison for generated text (compose files, SDF, parameter files).

A snapshot is a text file in the `data/` folder next to the test that owns it. A mismatch
fails with a unified diff and names the command that regenerates the files:

    pytest --update-snapshots <path of the test>

Regeneration rewrites only the files whose content changed. Review the diff of the data files
before committing them, since a snapshot records the generator's output as correct.
"""

import difflib
from pathlib import Path

from utils.file_system_utils import BACKEND_ROOT, REPO_ROOT

REGENERATE_HINT = "If the change is intended, regenerate the snapshots with: pytest --update-snapshots <test path>, then review and commit the data files."


def normalize_paths(text: str) -> str:
    """Replace the checkout location, which differs per machine and separator style, with placeholders."""
    for root, placeholder in ((BACKEND_ROOT, "<backend>"), (REPO_ROOT, "<repo>")):
        for variant in (root, root.replace("\\", "/")):
            text = text.replace(variant, placeholder)
    return text


class SnapshotChecker:
    def __init__(self, data_folder: Path, update: bool):
        self.data_folder = data_folder
        self.update = update

    def check(self, name: str, actual: str) -> None:
        """Compare `actual` (paths normalized) with data/<name>; rewrite the file when updating."""
        actual = normalize_paths(actual).replace("\r\n", "\n")
        if not actual.endswith("\n"):
            actual += "\n"
        path = self.data_folder / name
        if self.update:
            if not path.exists() or path.read_text(encoding="utf-8") != actual:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(actual, encoding="utf-8", newline="\n")
            return
        if not path.exists():
            raise AssertionError(f"No snapshot {path}. {REGENERATE_HINT}")
        expected = path.read_text(encoding="utf-8")
        if expected != actual:
            diff = "".join(difflib.unified_diff(expected.splitlines(keepends=True), actual.splitlines(keepends=True), fromfile=f"snapshot {name}", tofile="generated", n=2))
            raise AssertionError(f"Generated output differs from snapshot {name}:\n{diff}\n{REGENERATE_HINT}")
