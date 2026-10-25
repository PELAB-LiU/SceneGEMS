"""The fingerprints the sources of a checkout give, computed by deploy/scripts/build.sh."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

_GIT_BASH_CANDIDATES = (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe")


def _find_bash() -> str:
    """bash for the script. On Windows the bash on the PATH may be WSL's, so Git Bash is preferred."""
    override = os.environ.get("SCENEGEMS_BASH")
    if override:
        return override
    for candidate in _GIT_BASH_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    found = shutil.which("bash")
    if found is None:
        raise RuntimeError("bash is needed to compute image fingerprints; set SCENEGEMS_BASH")
    return found


def parse_fingerprint_listing(text: str) -> Dict[str, str]:
    """Parse the 'image fingerprint' lines printed by build.sh --fingerprints."""
    result: Dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def expected_fingerprints(repo_root: Optional[Path] = None) -> Dict[str, str]:
    """Image tag to fingerprint for every image of the checkout at repo_root (default: this checkout)."""
    root = repo_root or Path(__file__).resolve().parents[5]
    script = root / "deploy" / "scripts" / "build.sh"
    completed = subprocess.run([_find_bash(), script.as_posix(), "--fingerprints"], cwd=root, capture_output=True, text=True, check=True)
    return parse_fingerprint_listing(completed.stdout)
