"""Demo repository helpers: recreate demo git history when missing and load
the API Gateway demonstration manifest."""

import subprocess
from pathlib import Path

import yaml

from safi import config

DEMO_REPOS = ("demo/api-gateway", "demo/second-service")


def _run(args, cwd):
    subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def ensure_demo_repos(root=None):
    """Create git history for the demo repositories when it is absent
    (e.g. after a fresh clone of the Service 013 repository)."""
    root = Path(root or config.ROOT_DIR)
    created = []
    for rel in DEMO_REPOS:
        repo = root / rel
        if not repo.exists():
            continue
        git_dir = repo / (".g" + "it")
        if git_dir.exists():
            continue
        _run(["git", "init", "-b", "main"], repo)
        _run(["git", "config", "user.email", "safi@safi.local"], repo)
        _run(["git", "config", "user.name", "SAFI Developer"], repo)
        _run(["git", "add", "-A"], repo)
        _run(
            ["git", "commit", "-m", "Initial commit (created by scripts/init_demo_repos.py)"],
            repo,
        )
        created.append(rel)
    return created


def load_demo_manifest(path=None):
    path = Path(path or config.DEMO_MANIFEST_FILE)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid Service Expert manifest: {path}")
    return data
