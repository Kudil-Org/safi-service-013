import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(args, cwd):
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git invocation failed: {exc}") from exc
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "git failed").strip())
    return proc.stdout.strip()


def is_git_repo(path):
    try:
        return _run(["rev-parse", "--is-inside-work-tree"], path) == "true"
    except GitError:
        return False


def resolve_sha(path):
    return _run(["rev-parse", "HEAD"], path)


def resolve_branch(path):
    try:
        name = _run(["rev-parse", "--abbrev-ref", "HEAD"], path)
        return name
    except GitError:
        return ""


def git_state(path, max_commits=5, max_files=200):
    path = Path(path)
    if not path.exists():
        raise GitError(f"repository path does not exist: {path}")
    if not is_git_repo(path):
        raise GitError(f"not a git repository: {path}")
    sha = resolve_sha(path)
    branch = resolve_branch(path)
    dirty = bool(_run(["status", "--porcelain"], path))
    commits = []
    try:
        log = _run(["log", "-n", str(max_commits), "--pretty=%H\t%s"], path)
        for line in log.splitlines():
            if "\t" in line:
                csha, msg = line.split("\t", 1)
                commits.append({"sha": csha, "subject": msg})
    except GitError:
        pass
    files = []
    try:
        out = _run(["ls-files"], path)
        files = [f for f in out.splitlines() if f][:max_files]
    except GitError:
        pass
    return {
        "repo": str(path),
        "branch": branch,
        "sha": sha,
        "dirty": dirty,
        "commits": commits,
        "files": files,
    }


def short_sha(sha):
    return sha[:12] if sha else ""
