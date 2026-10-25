import subprocess

from scenegems_tool.cluster.release.__main__ import checkout_revision, main


def _git(root, *arguments):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *arguments], check=True, capture_output=True)


def test_the_revision_is_the_head_commit_and_changes_mark_it_dirty(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "file.txt")
    _git(tmp_path, "commit", "-q", "-m", "start")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert checkout_revision(tmp_path) == (head, False)
    (tmp_path / "file.txt").write_text("two\n", encoding="utf-8")
    assert checkout_revision(tmp_path) == (head, True)


def test_a_failure_is_one_error_line(tmp_path, capsys):
    assert main(["--out", str(tmp_path / "bundle"), "--repo-root", str(tmp_path / "not-a-checkout")]) == 1
    assert capsys.readouterr().err.startswith("error: ")
