"""Write a release bundle: `python -m scenegems_tool.cluster.release --out <folder>`.

Called by `./build.sh --release <folder>` after the images are built. The revision is the
checkout's HEAD commit; `dirty` says whether the checkout had uncommitted changes.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from scenegems_tool.cluster.release.bundle import build_bundle
from scenegems_tool.cluster.release.manifest import ReleaseError

REPO_ROOT = Path(__file__).resolve().parents[5]


def checkout_revision(repo_root: Path) -> Tuple[str, bool]:
    """HEAD commit of the checkout and whether it has uncommitted changes."""
    head = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, check=True).stdout
    return head, bool(status.strip())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenegems_tool.cluster.release", description="Write a SceneGEMS release bundle.")
    parser.add_argument("--out", type=Path, required=True, help="folder to write release.json and stacks/ into")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="the checkout the images were built from")
    arguments = parser.parse_args(argv)
    try:
        revision, dirty = checkout_revision(arguments.repo_root)
        release = build_bundle(arguments.out, arguments.repo_root, revision, dirty)
    except (ReleaseError, subprocess.CalledProcessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    state = " with uncommitted changes" if release.dirty else ""
    print(f"Release {release.revision[:12]}{state}: {len(release.images)} images, roles {', '.join(release.roles)}, written to {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
