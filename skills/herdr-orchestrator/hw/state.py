"""Persistent run state: one JSON document guarded by an flock, plus an append-only event log.

Layout under <project>/.hw/:
  state.json      authoritative state (tasks, workers, config)
  state.lock      flock target for every read-modify-write
  events.jsonl    append-only audit trail
  TODO.md         rendered view of state (regenerated on every mutation)
  tasks/<id>/     spec.md, prompt-N.md, result.md, notes
  logs/<worker>/  turn-N.json (spec), turn-N.jsonl (dsh events), turn-N.exit, turn-N.pid
  patches/        generated dsh model patches
  wt/<task>/      git worktrees
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = 1

TASK_STATUSES = ("todo", "running", "review", "done", "cancelled")
WORKER_STATUSES = ("idle", "running", "dead", "retired")


def now() -> float:
    return round(time.time(), 3)


def find_root(start: Path | None = None) -> Path:
    """Locate the project root: $HW_ROOT, else nearest ancestor containing .hw/."""
    env = os.environ.get("HW_ROOT")
    if env:
        return Path(env).resolve()
    p = (start or Path.cwd()).resolve()
    for cand in (p, *p.parents):
        if (cand / ".hw" / "state.json").exists():
            return cand
    raise SystemExit("hw: no .hw/state.json found here or above; run `hw init` first or set HW_ROOT")


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / ".hw"
        self.state_path = self.dir / "state.json"
        self.lock_path = self.dir / "state.lock"
        self.events_path = self.dir / "events.jsonl"

    # ---- paths -------------------------------------------------------
    def task_dir(self, task_id: str) -> Path:
        d = self.dir / "tasks" / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_dir(self, worker: str) -> Path:
        d = self.dir / "logs" / worker
        d.mkdir(parents=True, exist_ok=True)
        return d

    def wt_path(self, task_id: str) -> Path:
        return self.dir / "wt" / task_id

    # ---- locking -----------------------------------------------------
    @contextlib.contextmanager
    def lock(self, name: str = "state"):
        path = self.dir / f"{name}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # ---- state IO ----------------------------------------------------
    def exists(self) -> bool:
        return self.state_path.exists()

    def read(self) -> dict:
        with open(self.state_path) as fh:
            return json.load(fh)

    def _write(self, state: dict) -> None:
        state["updated_at"] = now()
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".state.", suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.state_path)

    @contextlib.contextmanager
    def mutate(self):
        """Read-modify-write under the state lock. Re-renders TODO.md afterwards.

        State is persisted even if the body raises: mutations mirror external side effects
        (panes spawned, turns started) that already happened and must not be forgotten.
        """
        from . import render  # local import avoids a cycle

        with self.lock("state"):
            state = self.read()
            try:
                yield state
            finally:
                self._write(state)
                render.write_todo(self, state)

    def create(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.lock("state"):
            if self.state_path.exists():
                raise SystemExit(f"hw: {self.state_path} already exists")
            self._write(state)

    # ---- events ------------------------------------------------------
    def event(self, event_type: str, **data) -> None:
        rec = {"ts": now(), "event": event_type, **data}
        line = json.dumps(rec, sort_keys=True) + "\n"
        # O_APPEND writes of a single line are atomic enough for our sizes; lock anyway.
        with self.lock("events"):
            with open(self.events_path, "a") as fh:
                fh.write(line)

    def events(self, limit: int | None = None) -> list[dict]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text().splitlines()
        if limit:
            lines = lines[-limit:]
        return [json.loads(l) for l in lines if l.strip()]


def new_state(run: str, goal: str, base_branch: str, config: dict) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "run": run,
        "goal": goal,
        "base_branch": base_branch,
        "created_at": now(),
        "config": config,
        "tab_id": None,
        "tasks": {},
        "workers": {},
        "notes": [],
        "seq": {"task": 0, "worker": 0},
    }
