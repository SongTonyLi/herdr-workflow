"""Git helpers: per-task worktrees and serialized merges into the base branch."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(cwd: Path | str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {(proc.stderr or proc.stdout).strip()}")
    return proc


def is_repo(root: Path) -> bool:
    return git(root, "rev-parse", "--git-dir", check=False).returncode == 0


def ensure_repo(root: Path) -> str:
    """Make sure root is a git repo with at least one commit; return the current branch."""
    if not is_repo(root):
        git(root, "init", "-q")
    if git(root, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:
        git(root, "commit", "-q", "--allow-empty", "-m", "hw: initial commit")
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


# Orchestrator state plus build/test junk that workers' tool runs leave behind; never auto-commit these.
EXCLUDES = [".hw/", "__pycache__/", "*.pyc", ".pytest_cache/", ".uv-cache/", ".uv-tools/", ".venv/", ".mypy_cache/", ".ruff_cache/"]


def exclude_hw(root: Path) -> None:
    gd = Path(git(root, "rev-parse", "--git-common-dir").stdout.strip())
    if not gd.is_absolute():
        gd = root / gd
    excl = gd / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    text = excl.read_text() if excl.exists() else ""
    have = set(text.split())
    missing = [p for p in EXCLUDES if p not in have]
    if missing:
        excl.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "\n".join(missing) + "\n")


def branch_exists(root: Path, branch: str) -> bool:
    return git(root, "rev-parse", "--verify", f"refs/heads/{branch}", check=False).returncode == 0


def add_worktree(root: Path, path: Path, branch: str, base: str) -> None:
    if path.exists() and (path / ".git").exists():
        return  # idempotent: resume/rescue reuse the same worktree
    path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "prune")
    if branch_exists(root, branch):
        git(root, "worktree", "add", str(path), branch)
    else:
        git(root, "worktree", "add", "-b", branch, str(path), base)


def remove_worktree(root: Path, path: Path) -> None:
    if path.exists():
        git(root, "worktree", "remove", "--force", str(path), check=False)
    git(root, "worktree", "prune", check=False)


def dirty(path: Path) -> str:
    return git(path, "status", "--porcelain", check=False).stdout


def commit_all(path: Path, message: str) -> bool:
    if not dirty(path).strip():
        return False
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return True


def diffstat(root: Path, base: str, branch: str) -> str:
    return git(root, "diff", "--stat", f"{base}...{branch}", check=False).stdout


def diff(root: Path, base: str, branch: str, max_chars: int = 12000) -> str:
    out = git(root, "diff", f"{base}...{branch}", check=False).stdout
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n... [diff truncated, {len(out)} chars total]\n"
    return out


def commits_ahead(root: Path, base: str, branch: str) -> int:
    r = git(root, "rev-list", "--count", f"{base}..{branch}", check=False)
    return int(r.stdout.strip() or 0)


def merge(root: Path, branch: str, message: str) -> tuple[bool, str]:
    """Merge branch into the currently checked-out base. Aborts cleanly on conflict."""
    r = git(root, "merge", "--no-ff", "-m", message, branch, check=False)
    if r.returncode == 0:
        return True, r.stdout
    conflicts = git(root, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    git(root, "merge", "--abort", check=False)
    return False, f"merge conflict in:\n{conflicts}\n{r.stdout}\n{r.stderr}"


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").stdout.strip()


def current_branch(root: Path) -> str:
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
