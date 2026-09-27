"""`hw` — orchestration mechanics for herdr + dsh worker panes.

The orchestrator (an LLM following SKILL.md) makes the judgment calls; this CLI
keeps state durable, consistent and race-free, and drives herdr/dsh/git.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from string import Template

from . import gitops, herdr, render, sched
from .state import Store, find_root, new_state, now

SKILL_DIR = Path(__file__).resolve().parent.parent
HW_BIN = SKILL_DIR / "bin" / "hw"
TEMPLATES = SKILL_DIR / "templates"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


# ---------------------------------------------------------------- helpers
def die(msg: str, code: int = 1):
    print(f"hw: {msg}", file=sys.stderr)
    raise SystemExit(code)


def out(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    elif isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, default=str))


def tpl(name: str, **kw) -> str:
    return Template((TEMPLATES / name).read_text()).safe_substitute({k: ("" if v is None else v) for k, v in kw.items()})


def load_models() -> dict:
    return json.loads((SKILL_DIR / "models.json").read_text())


def store() -> Store:
    return Store(find_root())


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def tail(path: Path, n: int = 40) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-n:])


def run_verify(cmd: str | None, cwd: Path, timeout: int = 900) -> tuple[bool | None, str]:
    if not cmd:
        return None, "(no verify command)"
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"verify timed out after {timeout}s"
    text = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode == 0, f"$ {cmd}\n(exit {p.returncode})\n" + "\n".join(text[-60:])


def session_from_log(logf: Path) -> str | None:
    if not logf.exists():
        return None
    with open(logf, errors="replace") as fh:
        for i, line in enumerate(fh):
            if i > 10:
                break
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "session":
                return e.get("sessionId")
    return None


def parse_result(path: Path) -> dict:
    if not path.exists():
        return {"status": None, "text": ""}
    text = path.read_text(errors="replace")
    m = re.search(r"STATUS:\s*\**\s*(DONE|PARTIAL|BLOCKED)", text, re.I)
    return {"status": m.group(1).upper() if m else None, "text": text.strip()}


def ensure_patch(st: Store, alias: str, models: dict) -> Path:
    """Generate a dsh --patch overlay that selects the model for this alias."""
    m = models[alias]
    patch = list(m.get("patch", [])) + [
        {
            "id": "agent-default-model",
            "name": "@deepseek-ai/dsh-agent-default-model",
            "config": {"provider": m["provider"], "model": m["model"]},
        }
    ]
    d = st.dir / "patches"
    d.mkdir(exist_ok=True)
    p = d / f"{alias}.yml"
    # JSON is valid YAML; dsh's loader accepts it.
    p.write_text(json.dumps(patch, indent=2) + "\n")
    return p


def deps_summary(st: Store, state: dict, task: dict) -> str:
    parts = []
    for d in task.get("deps", []):
        dt = state["tasks"].get(d)
        if not dt:
            continue
        res = parse_result(st.task_dir(d) / "result.md")["text"]
        parts.append(f"- {d} ({dt['title']}) — merged into `{state['base_branch']}`.\n" + (
            "  Report:\n" + "\n".join("    " + l for l in res.splitlines()[:15]) if res else ""))
    return "\n".join(parts) or "(none — this task has no dependencies)"


def files_rule(task: dict) -> str:
    f = task.get("files") or []
    return f" — you own these paths: {', '.join(f)}; avoid editing anything else unless strictly necessary" if f else ""


def task_vars(st: Store, state: dict, task: dict, worker: dict | None = None, **extra) -> dict:
    spec = (st.task_dir(task["id"]) / "spec.md").read_text() if (st.task_dir(task["id"]) / "spec.md").exists() else ""
    wt = task.get("worktree") or str(st.wt_path(task["id"]))
    v = dict(
        goal=state["goal"],
        task_id=task["id"],
        title=task["title"],
        kind=task.get("kind"),
        spec=spec,
        deps=deps_summary(st, state, task),
        worktree=wt,
        branch=task.get("branch") or f"hw/{task['id']}",
        verify=task.get("verify") or "(no automated check — self-review carefully)",
        result_file=str(st.task_dir(task["id"]) / "result.md"),
        files_rule=files_rule(task),
        worker=worker["name"] if worker else "",
        message="",
    )
    v.update(extra)
    return v


# ---------------------------------------------------------------- sync / reconcile
def finalize_turn(st: Store, state: dict, w: dict) -> dict | None:
    cur = w.get("current")
    if not cur:
        return None
    base = st.log_dir(w["name"]) / f"turn-{cur['turn']}"
    exit_file = Path(f"{base}.exit")
    if not exit_file.exists():
        return None
    ex = json.loads(exit_file.read_text())
    task = state["tasks"].get(cur.get("task"))
    ev = {"worker": w["name"], "model": w["model"], "turn": cur["turn"], "kind": cur["kind"],
          "task": cur.get("task"), "status": ex.get("status"), "rc": ex.get("rc"), "duration_s": ex.get("duration_s")}
    sid = ex.get("session_id") or session_from_log(Path(f"{base}.jsonl"))
    if task is not None and cur["kind"] in ("task", "steer", "resume", "handoff"):
        if sid:
            task["session"] = {"worker": w["name"], "id": sid}
        res = parse_result(st.task_dir(task["id"]) / "result.md")
        task["outcome"] = f"{ex.get('status')}/{res['status'] or 'no-report'}"
        # Stale reports from earlier turns must not count: only trust a report written during this turn.
        rpath = st.task_dir(task["id"]) / "result.md"
        fresh = rpath.exists() and rpath.stat().st_mtime >= cur.get("started_at", 0) - 1
        if ex.get("status") == "killed":
            # Infrastructure death (pane closed, runner lost): not the model's fault; resumable.
            task["interrupted"] = True
        elif ex.get("status") != "completed" or not fresh or res["status"] in ("BLOCKED", "PARTIAL"):
            task["failures"] = task.get("failures", 0) + 1
            if not fresh:
                task["outcome"] += "(stale)"
        if task["status"] == "running":
            task["status"] = "review"
            task["status_at"] = now()
        ev["result"] = res["status"]
        ev["fresh_report"] = fresh
    if cur["kind"] == "consult" and task is not None:
        ans = Path(cur.get("answer_file", ""))
        task.setdefault("consults", []).append({"worker": w["name"], "file": str(ans), "ok": ans.exists()})
    w.setdefault("history", []).append({**cur, "exit": ex.get("status"), "ended_at": ex.get("ended_at")})
    w["history"] = w["history"][-30:]
    w["current"] = None
    if w["status"] != "dead":
        w["status"] = "idle"
    w["status_at"] = now()
    st.event("turn_end", **ev)
    return ev


def sync_state(st: Store, state: dict, check_panes: bool = True) -> list[dict]:
    """Reconcile state with reality (exit files, pids, panes). Returns notable changes."""
    changes = []
    cfg = state["config"]
    for w in state["workers"].values():
        if w["status"] in ("retired",):
            continue
        alive = herdr.pane_alive(w.get("pane_id")) if check_panes else True
        if not alive and w["status"] != "dead":
            w["status"] = "dead"
            w["status_at"] = now()
            st.event("worker_dead", worker=w["name"], pane=w.get("pane_id"))
            changes.append({"type": "worker_dead", "worker": w["name"]})
        ev = finalize_turn(st, state, w)
        if ev:
            changes.append({"type": "turn_end", **ev})
            continue
        cur = w.get("current")
        if cur:
            base = st.log_dir(w["name"]) / f"turn-{cur['turn']}"
            pidf = Path(f"{base}.pid")
            pid_ok = pidf.exists() and pid_alive(int(pidf.read_text().strip() or 0))
            age = time.time() - cur.get("started_at", time.time())
            if not pid_ok and (not alive or age > 20):
                if not cur.get("lost"):
                    cur["lost"] = True
                    st.event("turn_lost", worker=w["name"], turn=cur["turn"], task=cur.get("task"))
                    changes.append({"type": "turn_lost", "worker": w["name"], "task": cur.get("task")})
            elif pid_ok:
                logf = Path(f"{base}.jsonl")
                last = logf.stat().st_mtime if logf.exists() else cur.get("started_at", time.time())
                idle_for = time.time() - last
                stalled = idle_for > cfg.get("stall_seconds", 600)
                if stalled and not cur.get("stalled"):
                    st.event("turn_stalled", worker=w["name"], task=cur.get("task"), idle_s=int(idle_for))
                    changes.append({"type": "stalled", "worker": w["name"], "task": cur.get("task"), "idle_s": int(idle_for)})
                cur["stalled"] = stalled
                cur["idle_s"] = int(idle_for)
    return changes


# ---------------------------------------------------------------- panes / workers
def ensure_tab(st: Store, state: dict) -> str | None:
    """Return a live pane in the run's tab to split from, or None if a new tab is needed."""
    for w in sorted(state["workers"].values(), key=lambda w: -w["seq"]):
        if w["status"] in ("idle", "running", "dead") and w.get("pane_id") and herdr.pane_alive(w["pane_id"]):
            return w["pane_id"]
    return None


def spawn_worker(st: Store, state: dict, alias: str, name: str | None = None, reuse: dict | None = None) -> dict:
    models = state["config"]["models"]
    if alias not in models:
        die(f"unknown model alias {alias!r}; known: {', '.join(models)}")
    if not herdr.in_herdr():
        die("not running inside herdr (HERDR_ENV != 1)")
    with st.lock("panes"):  # serialize layout changes
        anchor = ensure_tab(st, state)
        if anchor:
            pane = herdr.split_largest(anchor, str(st.root))
        else:
            ws = os.environ.get("HW_WORKSPACE") or os.environ.get("HERDR_WORKSPACE_ID")
            if not ws:
                die("no HERDR_WORKSPACE_ID to create the worker tab in")
            tab, pane = herdr.create_tab(ws, str(st.root), f"hw:{state['run']}")
            state["tab_id"] = tab
    if reuse:
        w = reuse
        w.update(pane_id=pane, status="idle", status_at=now(), current=None)
        w["respawns"] = w.get("respawns", 0) + 1
    else:
        state["seq"]["worker"] += 1
        n = state["seq"]["worker"]
        name = name or f"{alias}-{n}"
        if not NAME_RE.match(name):
            die(f"bad worker name {name!r}")
        if name in state["workers"]:
            die(f"worker {name} already exists")
        w = {"name": name, "seq": n, "model": alias, "pane_id": pane, "status": "idle",
             "status_at": now(), "created_at": now(), "turns": 0, "current": None, "history": []}
        state["workers"][name] = w
    herdr.rename(pane, f"hw {w['name']} [{alias}]")
    ensure_patch(st, alias, models)
    st.event("worker_spawn", worker=w["name"], model=alias, pane=pane, respawn=bool(reuse))
    wait_shell_ready(pane)
    return w


def wait_shell_ready(pane: str, timeout: float = 15) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        r = herdr.call("pane", "process-info", "--pane", pane, check=False)
        pi = r.get("result", {}).get("process_info", {})
        if pi and pi.get("foreground_process_group_id") == pi.get("shell_pid"):
            return True
        time.sleep(0.5)
    return False


def pick_worker(st: Store, state: dict, target: str | None, task: dict, exclude: str | None = None) -> dict:
    """Resolve a worker name or model alias (or None = by tier) to an idle worker, spawning if needed."""
    workers = state["workers"]
    if target and target in workers:
        w = workers[target]
        if w["status"] == "dead":
            spawn_worker(st, state, w["model"], reuse=w)
        elif w["status"] != "idle":
            die(f"worker {target} is {w['status']}; wait, steer, or choose another")
        return w
    aliases = [target] if target else sched.candidates(task, state["config"])
    for alias in aliases:
        if alias not in state["config"]["models"]:
            die(f"unknown worker/model {alias!r}")
        for w in sorted(workers.values(), key=lambda w: w["seq"]):
            if w["model"] == alias and w["status"] == "idle" and w["name"] != exclude:
                return w
    live = sum(1 for w in workers.values() if w["status"] in ("idle", "running"))
    alias = aliases[0]
    if live >= state["config"].get("max_workers", 4) and not target:
        die(f"no idle {'/'.join(aliases)} worker and max_workers reached; wait or pass --to explicitly")
    return spawn_worker(st, state, alias)


# ---------------------------------------------------------------- turns
def start_turn(st: Store, state: dict, w: dict, task: dict, prompt: str, kind: str,
               session_id: str | None = None, cwd: str | None = None, extra: dict | None = None) -> dict:
    if w["status"] == "dead" or not herdr.pane_alive(w["pane_id"]):
        spawn_worker(st, state, w["model"], reuse=w)
    if w.get("current"):
        die(f"worker {w['name']} already has an active turn")
    if not wait_shell_ready(w["pane_id"], timeout=10):
        die(f"pane {w['pane_id']} of {w['name']} is not at an idle shell prompt")
    w["turns"] = w.get("turns", 0) + 1
    n = w["turns"]
    logd = st.log_dir(w["name"])
    for suffix in (".exit", ".pid", ".jsonl"):
        p = logd / f"turn-{n}{suffix}"
        if p.exists():  # leftover from a crashed attempt at the same number: move aside
            p.rename(p.with_name(p.name + f".stale-{int(time.time())}"))
    pfile = st.task_dir(task["id"]) / f"prompt-{w['name']}-{n}.md"
    pfile.write_text(prompt)
    models = state["config"]["models"]
    spec = {
        "worker": w["name"], "model": w["model"], "turn": n, "task": task["id"], "kind": kind,
        "cwd": cwd or task["worktree"], "prompt_file": str(pfile),
        "patch": str(ensure_patch(st, w["model"], models)),
        "profile": state["config"].get("dsh_profile", "headless"),
        "session_id": session_id,
        "dsh_bin": os.environ.get("HW_DSH_BIN"),
        "env": worker_env(state, cwd or task["worktree"]),
    }
    spec_path = logd / f"turn-{n}.json"
    spec_path.write_text(json.dumps(spec, indent=2))
    cmd = " ".join(shlex.quote(x) for x in (sys.executable, str(HW_BIN), "_turn", str(spec_path)))
    herdr.run(w["pane_id"], cmd)
    w["current"] = {"kind": kind, "task": task["id"], "turn": n, "started_at": now(), **(extra or {})}
    w["status"] = "running"
    w["status_at"] = now()
    if kind != "consult":
        task["status"] = "running"
        task["status_at"] = now()
        task["worker"] = w["name"]
        task["attempts"] = task.get("attempts", 0) + 1
        stats = state.setdefault("stats", {}).setdefault("assigned", {})
        stats[w["model"]] = stats.get(w["model"], 0) + 1
    st.event("turn_start", worker=w["name"], model=w["model"], task=task["id"], kind=kind, turn=n,
             resume=bool(session_id))
    return {"worker": w["name"], "model": w["model"], "pane": w["pane_id"], "task": task["id"], "turn": n, "kind": kind}


def worker_env(state: dict, cwd: str) -> dict:
    """Env for dsh turns. dsh sandboxes writes to the worktree (+ temp dirs), so tool caches go to tmp."""
    import tempfile

    tmp = tempfile.gettempdir().rstrip("/")
    return {k: str(v).replace("{tmp}", tmp).replace("{worktree}", cwd)
            for k, v in (state["config"].get("worker_env") or {}).items()}


def interrupt_worker(st: Store, state: dict, w: dict, timeout: float = 45) -> dict | None:
    cur = w.get("current")
    if not cur:
        return None
    exit_file = st.log_dir(w["name"]) / f"turn-{cur['turn']}.exit"
    if herdr.pane_alive(w["pane_id"]) and not exit_file.exists():
        herdr.send_keys(w["pane_id"], "ctrl+c")
        end = time.time() + timeout
        while time.time() < end and not exit_file.exists():
            time.sleep(0.5)
        if not exit_file.exists():
            herdr.send_keys(w["pane_id"], "ctrl+c")
            time.sleep(3)
    if not exit_file.exists():
        # Runner is gone without evidence: synthesize an exit so the state machine can move on.
        exit_file.write_text(json.dumps({"rc": None, "status": "interrupted", "session_id": None,
                                         "final": None, "error": "forced by hw", "ended_at": now()}))
    st.event("interrupt", worker=w["name"], task=cur.get("task"), turn=cur["turn"])
    return finalize_turn(st, state, w)


def prepare_worktree(st: Store, state: dict, task: dict) -> None:
    wt = st.wt_path(task["id"])
    branch = task.get("branch") or f"hw/{task['id']}"
    with st.lock("git"):
        gitops.add_worktree(st.root, wt, branch, state["base_branch"])
    task["worktree"] = str(wt)
    task["branch"] = branch


def assign(st: Store, state: dict, task: dict, w: dict) -> dict:
    if task["status"] not in ("todo",):
        die(f"task {task['id']} is {task['status']}, not todo")
    if not sched.deps_done(task, state["tasks"]):
        die(f"task {task['id']} has unfinished deps: {task.get('deps')}")
    prepare_worktree(st, state, task)
    prompt = tpl("worker_prompt.md", **task_vars(st, state, task, w))
    return start_turn(st, state, w, task, prompt, "task")


# ---------------------------------------------------------------- commands
def cmd_init(a):
    root = Path(a.root or os.getcwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    base = gitops.ensure_repo(root)
    gitops.exclude_hw(root)
    cfg = load_models()
    if a.max_workers:
        cfg["max_workers"] = a.max_workers
    run = a.run or root.name.lower().replace(" ", "-")[:24]
    st.create(new_state(run, a.goal, base, cfg))
    st.event("init", run=run, goal=a.goal, base=base)
    render.write_todo(st, st.read())
    print(f"initialized run {run!r} in {st.dir} (base branch {base})")


def cmd_config(a):
    st = store()
    with st.mutate() as s:
        for kv in a.set or []:
            k, _, v = kv.partition("=")
            try:
                val = json.loads(v)
            except json.JSONDecodeError:
                val = v
            node = s["config"]
            keys = k.split(".")
            for key in keys[:-1]:
                node = node.setdefault(key, {})
            node[keys[-1]] = val
        cfg = s["config"]
    out(cfg, True)


def cmd_task_add(a):
    st = store()
    spec = a.spec or ""
    if a.spec_file:
        spec = Path(a.spec_file).read_text()
    with st.mutate() as s:
        tid = a.id
        if not NAME_RE.match(tid):
            die(f"task id must match {NAME_RE.pattern}")
        if tid in s["tasks"]:
            die(f"task {tid} exists")
        for d in a.deps or []:
            if d not in s["tasks"]:
                die(f"unknown dep {d}")
        if a.model and a.model not in s["config"]["models"]:
            die(f"unknown model {a.model}")
        s["seq"]["task"] += 1
        s["tasks"][tid] = {
            "id": tid, "seq": s["seq"]["task"], "title": a.title, "kind": a.kind, "deps": a.deps or [],
            "files": a.files or [], "verify": a.verify, "priority": a.priority, "model": a.model,
            "status": "todo", "status_at": now(), "attempts": 0, "failures": 0,
        }
        (st.task_dir(tid) / "spec.md").write_text(spec.strip() + "\n")
    st.event("task_add", task=tid, kind=a.kind, deps=a.deps or [])
    print(f"added {tid}")


def cmd_task_update(a):
    st = store()
    with st.mutate() as s:
        t = s["tasks"].get(a.id) or die(f"no task {a.id}")
        for field in ("title", "kind", "verify", "model", "note"):
            v = getattr(a, field)
            if v is not None:
                t[field] = v or None
        if a.priority is not None:
            t["priority"] = a.priority
        if a.deps is not None:
            t["deps"] = a.deps
        if a.files is not None:
            t["files"] = a.files
        if a.status:
            t["status"] = a.status
            t["status_at"] = now()
        if a.spec is not None or a.spec_file:
            (st.task_dir(a.id) / "spec.md").write_text((Path(a.spec_file).read_text() if a.spec_file else a.spec) + "\n")
    st.event("task_update", task=a.id, **{k: v for k, v in vars(a).items() if k in ("status", "note", "model") and v})
    print(f"updated {a.id}")


def cmd_task_show(a):
    st = store()
    s = st.read()
    t = s["tasks"].get(a.id) or die(f"no task {a.id}")
    d = dict(t)
    d["spec"] = (st.task_dir(a.id) / "spec.md").read_text()
    d["result"] = parse_result(st.task_dir(a.id) / "result.md")
    d["effective_tier"] = sched.tier_for(t, s["config"])
    out(d, True)


def cmd_worker_spawn(a):
    st = store()
    with st.mutate() as s:
        w = spawn_worker(st, s, a.model, a.name)
    print(json.dumps({"worker": w["name"], "pane": w["pane_id"], "model": w["model"]}))


def cmd_worker_retire(a):
    st = store()
    with st.mutate() as s:
        w = s["workers"].get(a.name) or die(f"no worker {a.name}")
        if w.get("current") and not a.force:
            die(f"{a.name} is busy; use --force to interrupt")
        if w.get("current"):
            interrupt_worker(st, s, w)
        if w.get("pane_id"):
            herdr.close(w["pane_id"])
        w["status"] = "retired"
        w["status_at"] = now()
    st.event("worker_retire", worker=a.name)
    print(f"retired {a.name}")


def cmd_assign(a):
    st = store()
    with st.mutate() as s:
        t = s["tasks"].get(a.task) or die(f"no task {a.task}")
        w = pick_worker(st, s, a.to, t)
        r = assign(st, s, t, w)
    print(json.dumps(r))


def cmd_schedule(a):
    st = store()
    with st.mutate() as s:
        sync_state(st, s)
        actions = sched.plan(s)
        done = []
        if a.apply:
            for act in actions:
                t = s["tasks"][act["task"]]
                w = s["workers"][act["worker"]] if "worker" in act else spawn_worker(st, s, act["spawn"])
                done.append(assign(st, s, t, w))
    out({"planned": actions, "started": done} if a.apply else {"planned": actions}, True)


def status_obj(st: Store, s: dict) -> dict:
    tasks = []
    for t in sorted(s["tasks"].values(), key=lambda t: t["seq"]):
        tasks.append({k: t.get(k) for k in ("id", "title", "kind", "status", "worker", "deps", "attempts", "failures", "outcome", "note")}
                     | {"tier": sched.tier_for(t, s["config"])})
    workers = []
    for w in sorted(s["workers"].values(), key=lambda w: w["seq"]):
        workers.append({k: w.get(k) for k in ("name", "model", "status", "pane_id", "current", "turns")})
    return {"run": s["run"], "goal": s["goal"], "base": s["base_branch"], "tasks": tasks, "workers": workers,
            "ready": [t["id"] for t in sched.ready_tasks(s)],
            "planned": sched.plan(s)}


def cmd_status(a):
    st = store()
    with st.mutate() as s:
        changes = sync_state(st, s)
    s = st.read()
    if a.json:
        out(status_obj(st, s) | {"changes": changes}, True)
    else:
        print((st.dir / "TODO.md").read_text())
        if changes:
            print("changes since last sync:")
            for c in changes:
                print("  ", json.dumps(c))


def cmd_sync(a):
    st = store()
    with st.mutate() as s:
        changes = sync_state(st, s)
    out(changes, True)


WAIT_EVENTS = ("turn_end", "turn_lost", "worker_dead", "turn_stalled")


def cmd_wait(a):
    """Block until some turn ends / stalls / is lost (or none are running, with --all).

    Reads the durable event log rather than this process's own sync results, so concurrent
    `hw status`/`hw wait` callers can't swallow each other's events.
    """
    st = store()
    since = a.since if a.since is not None else now()
    deadline = time.time() + a.timeout if a.timeout else None
    while True:
        with st.mutate() as s:
            sync_state(st, s)
            running = [w["name"] for w in s["workers"].values() if w.get("current") and not w["current"].get("lost")]
            review = [t["id"] for t in s["tasks"].values() if t["status"] == "review"]
            ready = [t["id"] for t in sched.ready_tasks(s)]
        evs = [e for e in st.events(500) if e["ts"] >= since and e["event"] in WAIT_EVENTS]
        done = (evs and not a.all) or not running or (deadline and time.time() > deadline)
        if done:
            out({"events": evs, "still_running": running, "needs_review": review, "ready": ready,
                 "since": since, **({"timeout": True} if running and not evs and deadline and time.time() > deadline else {})}, True)
            return
        time.sleep(a.interval)


def cmd_review(a):
    st = store()
    with st.mutate() as s:
        sync_state(st, s)
    s = st.read()
    t = s["tasks"].get(a.task) or die(f"no task {a.task}")
    wt = Path(t.get("worktree") or st.wt_path(a.task))
    info = {"task": a.task, "status": t["status"], "worker": t.get("worker"), "outcome": t.get("outcome"),
            "attempts": t.get("attempts"), "failures": t.get("failures")}
    if wt.exists():
        info["uncommitted"] = gitops.dirty(wt)
        info["commits_ahead"] = gitops.commits_ahead(st.root, s["base_branch"], t["branch"])
        info["diffstat"] = gitops.diffstat(st.root, s["base_branch"], t["branch"])
        if not a.no_verify:
            ok, vout = run_verify(t.get("verify"), wt)
            info["verify_ok"] = ok
            info["verify_output"] = vout
            with st.mutate() as s2:
                s2["tasks"][a.task]["last_verify"] = {"ok": ok, "output": vout[-4000:], "at": now()}
    info["result"] = parse_result(st.task_dir(a.task) / "result.md")["text"]
    w = s["workers"].get(t.get("worker") or "")
    if w and w.get("history"):
        last = w["history"][-1]
        ex = st.log_dir(w["name"]) / f"turn-{last['turn']}.exit"
        if ex.exists():
            info["last_turn"] = json.loads(ex.read_text())
    if a.diff and wt.exists():
        info["diff"] = gitops.diff(st.root, s["base_branch"], t["branch"])
    out(info, True)


def cmd_merge(a):
    st = store()
    with st.lock("merge"):
        with st.mutate() as s:
            sync_state(st, s)
        s = st.read()
        t = s["tasks"].get(a.task) or die(f"no task {a.task}")
        if t["status"] not in ("review", "running") and not a.force:
            die(f"task {a.task} is {t['status']}")
        if t["status"] == "running":
            die(f"task {a.task} is still running; wait for it first")
        wt = Path(t["worktree"])
        if gitops.commit_all(wt, f"hw: {a.task} uncommitted leftovers"):
            st.event("autocommit", task=a.task)
        if gitops.current_branch(st.root) != s["base_branch"]:
            die(f"project root is not on base branch {s['base_branch']}")
        if gitops.dirty(st.root, tracked_only=True).strip():
            die("project root has uncommitted changes to tracked files; commit or stash them before merging")
        if gitops.commits_ahead(st.root, s["base_branch"], t["branch"]) == 0:
            die(f"branch {t['branch']} has no commits beyond {s['base_branch']}")
        before = gitops.head(st.root)
        ok, msg = gitops.merge(st.root, t["branch"], f"hw: merge {a.task} — {t['title']}")
        verify_ok, vout = (None, "")
        if ok and not a.no_verify:
            verify_ok, vout = run_verify(t.get("verify"), st.root)
            if verify_ok is False:
                gitops.git(st.root, "reset", "--hard", before)
                ok = False
                msg = "post-merge verification failed on base; merge rolled back\n" + vout
        with st.mutate() as s:
            t = s["tasks"][a.task]
            if ok:
                t["status"] = "done"
                t["status_at"] = now()
                t["merged_at"] = now()
                t["note"] = None
            else:
                t["status"] = "review"
                t["note"] = msg.strip().splitlines()[0][:200]
                t["merge_error"] = msg[-4000:]
        st.event("merge", task=a.task, ok=ok, verify=verify_ok)
    if ok and not a.keep_worktree:
        with st.lock("git"):
            gitops.remove_worktree(st.root, wt)
    out({"task": a.task, "merged": ok, "detail": msg[-3000:], "verify": vout[-2000:]}, True)
    if not ok:
        raise SystemExit(3)


def cmd_steer(a):
    st = store()
    msg = a.message or (Path(a.file).read_text() if a.file else die("need -m or --file"))
    with st.mutate() as s:
        sync_state(st, s)
        t = s["tasks"].get(a.task) or die(f"no task {a.task}")
        w = s["workers"].get(t.get("worker") or "") or die(f"task {a.task} has no worker; use assign")
        if w.get("current"):
            if w["current"].get("task") != a.task:
                die(f"{w['name']} is busy with {w['current'].get('task')}")
            interrupt_worker(st, s, w)
        if a.count_failure:
            t["failures"] = t.get("failures", 0) + 1
        sess = (t.get("session") or {})
        sid = sess.get("id") if sess.get("worker") == w["name"] else None
        if sid:
            prompt = tpl("steer_prompt.md", **task_vars(st, s, t, w, message=msg))
        else:  # no resumable session: re-send full context
            prompt = tpl("worker_prompt.md", **task_vars(st, s, t, w)) + "\n\n## Orchestrator note\n" + msg
        prepare_worktree(st, s, t)
        r = start_turn(st, s, w, t, prompt, "steer", session_id=sid)
    st.event("steer", task=a.task, worker=w["name"], message=msg[:500])
    print(json.dumps(r))


def cmd_interrupt(a):
    st = store()
    with st.mutate() as s:
        w = s["workers"].get(a.worker) or die(f"no worker {a.worker}")
        r = interrupt_worker(st, s, w)
    out(r or {"note": "nothing running"}, True)


def _context_for(st: Store, s: dict, t: dict) -> dict:
    wt = Path(t["worktree"]) if t.get("worktree") else None
    d = gitops.diff(st.root, s["base_branch"], t["branch"], 10000) if t.get("branch") and gitops.branch_exists(st.root, t["branch"]) else ""
    if wt and wt.exists():
        unc = gitops.git(wt, "diff", check=False).stdout
        if unc.strip():
            d += "\n# --- uncommitted changes ---\n" + unc[:6000]
    lv = t.get("last_verify") or {}
    vout = lv.get("output") or t.get("merge_error") or "(not run yet)"
    prev = parse_result(st.task_dir(t["id"]) / "result.md")["text"] or "(no report written)"
    return {"diff": d or "(no changes yet)", "verify_output": vout, "prev_result": prev}


def cmd_rescue(a):
    st = store()
    with st.mutate() as s:
        sync_state(st, s)
        t = s["tasks"].get(a.task) or die(f"no task {a.task}")
        prev = s["workers"].get(t.get("worker") or "")
        if prev and prev.get("current") and prev["current"].get("task") == a.task:
            interrupt_worker(st, s, prev)
        if t["status"] == "todo":
            t["failures"] = max(t.get("failures", 0), 1)
        target = a.to
        if not target:
            # escalate: prefer a stronger tier than the previous worker's
            t_tier = sched.tier_for(t, s["config"])
            order = s["config"].get("tier_order", ["fast", "reason"])
            if prev and s["config"]["models"][prev["model"]]["tier"] == t_tier and t_tier != order[-1]:
                t_tier = order[order.index(t_tier) + 1]
            target = next((al for al, m in s["config"]["models"].items() if m["tier"] == t_tier), None)
        w = pick_worker(st, s, target, t, exclude=prev["name"] if prev else None)
        prepare_worktree(st, s, t)
        ctx = _context_for(st, s, t)
        prompt = tpl("handoff_prompt.md", **task_vars(
            st, s, t, w, message=a.message or "(none)", prev_worker=prev["name"] if prev else "(none)",
            prev_model=prev["model"] if prev else "-", attempts=t.get("attempts", 0), **ctx))
        t["status"] = "running"
        r = start_turn(st, s, w, t, prompt, "handoff")
    st.event("rescue", task=a.task, from_worker=prev["name"] if prev else None, to_worker=w["name"], model=w["model"])
    print(json.dumps(r))


def cmd_consult(a):
    st = store()
    with st.mutate() as s:
        sync_state(st, s)
        t = s["tasks"].get(a.task) or die(f"no task {a.task}")
        if not t.get("worktree"):
            die(f"task {a.task} has no worktree yet")
        target = a.to or next(al for al, m in s["config"]["models"].items() if m["tier"] == "reason")
        w = pick_worker(st, s, target, t, exclude=t.get("worker"))
        n = len(t.get("consults", [])) + 1
        ans = st.task_dir(a.task) / f"consult-{n}.md"
        prompt = tpl("consult_prompt.md", **task_vars(st, s, t, w, message=a.message, task_worker=t.get("worker"),
                                                        answer_file=str(ans), **_context_for(st, s, t)))
        r = start_turn(st, s, w, t, prompt, "consult", cwd=t["worktree"], extra={"answer_file": str(ans)})
    st.event("consult", task=a.task, worker=w["name"], question=a.message[:300])
    print(json.dumps(r | {"answer_file": str(ans)}))


def cmd_resume(a):
    """Reconcile after a crash/restart and restart interrupted turns with their dsh sessions.

    Interrupted = the runner was killed (pane closed, SIGHUP) or vanished without an exit file.
    Running turns whose runner is still alive are left alone: panes outlive the orchestrator.
    """
    st = store()
    report = {"changes": [], "resumed": [], "respawned": [], "left_alone": []}
    with st.mutate() as s:
        report["changes"] = sync_state(st, s)
        # 1. close out lost turns (no exit file, runner gone) as "killed"
        for w in s["workers"].values():
            cur = w.get("current")
            if cur and cur.get("lost"):
                exit_file = st.log_dir(w["name"]) / f"turn-{cur['turn']}.exit"
                if not exit_file.exists():
                    exit_file.write_text(json.dumps({"rc": None, "status": "killed", "session_id": None,
                                                     "final": None, "error": "lost (pane or runner died)",
                                                     "ended_at": now()}))
                finalize_turn(st, s, w)
            elif cur:
                report["left_alone"].append(w["name"])
        # 2. restart every interrupted task on its own worker (same dsh session, same worktree)
        for t in sorted(s["tasks"].values(), key=lambda t: t["seq"]):
            if not t.get("interrupted") or t["status"] in ("done", "cancelled"):
                continue
            w = s["workers"].get(t.get("worker") or "")
            if w is None or w["status"] == "retired" or w.get("current"):
                w = pick_worker(st, s, None, t)
            if w["status"] == "dead" or not herdr.pane_alive(w["pane_id"]):
                spawn_worker(st, s, w["model"], reuse=w)
                report["respawned"].append(w["name"])
            sess = t.get("session") or {}
            sid = sess.get("id") if sess.get("worker") == w["name"] else None
            if sid:
                prompt = tpl("resume_prompt.md", **task_vars(st, s, t, w, message=a.message or ""))
            else:
                prompt = tpl("worker_prompt.md", **task_vars(st, s, t, w)) + "\n\n" + tpl(
                    "resume_prompt.md", **task_vars(st, s, t, w, message=a.message or ""))
            t["interrupted"] = False
            t["status"] = "running"
            prepare_worktree(st, s, t)
            r = start_turn(st, s, w, t, prompt, "resume", session_id=sid)
            report["resumed"].append(r | {"session": sid})
        # 3. dead idle workers: optionally recreate their panes
        for w in s["workers"].values():
            if w["status"] == "dead" and not w.get("current") and a.respawn_idle:
                spawn_worker(st, s, w["model"], reuse=w)
                report["respawned"].append(w["name"])
        # 4. tasks marked running with no live turn behind them
        for t in s["tasks"].values():
            if t["status"] == "running":
                w = s["workers"].get(t.get("worker") or "")
                if not w or not w.get("current") or w["current"].get("task") != t["id"]:
                    t["status"] = "review"
                    t["note"] = "was running but no live turn found during resume"
                    report["changes"].append({"type": "orphan_task", "task": t["id"]})
    st.event("resume", resumed=[r["worker"] for r in report["resumed"]], respawned=report["respawned"])
    out(report, True)


def cmd_note(a):
    st = store()
    with st.mutate() as s:
        s["notes"].append({"at": now(), "text": a.text})
    st.event("note", text=a.text)


def cmd_log(a):
    st = store()
    s = st.read()
    w = s["workers"].get(a.worker) or die(f"no worker {a.worker}")
    n = a.turn or (w["current"]["turn"] if w.get("current") else w.get("turns"))
    if not n:
        die("no turns yet")
    base = st.log_dir(a.worker) / f"turn-{n}"
    if a.pane:
        print(herdr.read(w["pane_id"], a.lines))
        return
    lines = []
    for line in Path(f"{base}.jsonl").read_text().splitlines() if Path(f"{base}.jsonl").exists() else []:
        try:
            from .turn import render_event
            r = render_event(json.loads(line))
        except Exception:  # noqa: BLE001
            r = line
        if r:
            lines.append(r)
    print("\n".join(lines[-a.lines:]))
    ex = Path(f"{base}.exit")
    if ex.exists():
        print("\nexit:", ex.read_text())


def cmd_todo(a):
    st = store()
    s = st.read()
    render.write_todo(st, s)
    print((st.dir / "TODO.md").read_text())


def cmd_events(a):
    st = store()
    for e in st.events(a.limit):
        print(json.dumps(e))


def cmd_gc(a):
    st = store()
    with st.mutate() as s:
        sync_state(st, s)
        busy = [w["name"] for w in s["workers"].values() if w.get("current")]
        if busy and not a.force:
            die(f"workers still busy: {busy}")
        for w in s["workers"].values():
            if w["status"] in ("idle", "running", "dead"):
                if w.get("current"):
                    interrupt_worker(st, s, w)
                if w.get("pane_id"):
                    herdr.close(w["pane_id"])
                w["status"] = "retired"
        for t in s["tasks"].values():
            if t["status"] in ("done", "cancelled") and t.get("worktree"):
                with st.lock("git"):
                    gitops.remove_worktree(st.root, Path(t["worktree"]))
    st.event("gc")
    print("closed run panes and removed finished worktrees")


def cmd_turn(a):
    from .turn import run
    raise SystemExit(run(a.spec))


# ---------------------------------------------------------------- argparse
def build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hw", description="herdr multi-agent workflow mechanics")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create .hw/ run state in a project (git-inits if needed)")
    s.add_argument("--goal", required=True)
    s.add_argument("--run")
    s.add_argument("--root")
    s.add_argument("--max-workers", type=int)
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("config", help="show or set config (dotted keys, JSON values)")
    s.add_argument("--set", action="append", metavar="KEY=VALUE")
    s.set_defaults(fn=cmd_config)

    t = sub.add_parser("task", help="manage tasks").add_subparsers(dest="tcmd", required=True)
    s = t.add_parser("add")
    s.add_argument("id")
    s.add_argument("--title", required=True)
    s.add_argument("--kind", default="implement")
    s.add_argument("--spec")
    s.add_argument("--spec-file")
    s.add_argument("--deps", nargs="*")
    s.add_argument("--files", nargs="*")
    s.add_argument("--verify")
    s.add_argument("--priority", type=int, default=0)
    s.add_argument("--model", help="pin to a model alias")
    s.set_defaults(fn=cmd_task_add)
    s = t.add_parser("update")
    s.add_argument("id")
    for f in ("title", "kind", "verify", "model", "note", "spec", "spec_file"):
        s.add_argument("--" + f.replace("_", "-"), dest=f)
    s.add_argument("--priority", type=int)
    s.add_argument("--deps", nargs="*")
    s.add_argument("--files", nargs="*")
    s.add_argument("--status", choices=["todo", "review", "done", "cancelled"])
    s.set_defaults(fn=cmd_task_update)
    s = t.add_parser("show")
    s.add_argument("id")
    s.set_defaults(fn=cmd_task_show)

    w = sub.add_parser("worker", help="manage worker panes").add_subparsers(dest="wcmd", required=True)
    s = w.add_parser("spawn")
    s.add_argument("--model", required=True)
    s.add_argument("--name")
    s.set_defaults(fn=cmd_worker_spawn)
    s = w.add_parser("retire")
    s.add_argument("name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_worker_retire)

    s = sub.add_parser("assign", help="start a todo task on a worker (name or model alias; default by tier)")
    s.add_argument("task")
    s.add_argument("--to")
    s.set_defaults(fn=cmd_assign)

    s = sub.add_parser("schedule", help="plan (and with --apply, start) balanced assignments for ready tasks")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("status", help="sync with reality and print the todo board")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    sub.add_parser("todo").set_defaults(fn=cmd_todo)

    s = sub.add_parser("wait", help="block until a turn ends/stalls/dies (--all: until none running)")
    s.add_argument("--timeout", type=float, default=0)
    s.add_argument("--interval", type=float, default=3)
    s.add_argument("--all", action="store_true")
    s.add_argument("--since", type=float, help="report events since this unix ts (default: now)")
    s.set_defaults(fn=cmd_wait)

    s = sub.add_parser("review", help="verify + report for a task's branch")
    s.add_argument("task")
    s.add_argument("--diff", action="store_true")
    s.add_argument("--no-verify", action="store_true")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("merge", help="merge a reviewed task into base (serialized, verified, rollback on failure)")
    s.add_argument("task")
    s.add_argument("--no-verify", action="store_true")
    s.add_argument("--keep-worktree", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_merge)

    s = sub.add_parser("steer", help="send guidance to the task's worker (resumes its dsh session)")
    s.add_argument("task")
    s.add_argument("-m", "--message")
    s.add_argument("--file")
    s.add_argument("--count-failure", action="store_true", help="count this as a failed attempt (drives escalation)")
    s.set_defaults(fn=cmd_steer)

    s = sub.add_parser("interrupt", help="ctrl+c a worker's running turn")
    s.add_argument("worker")
    s.set_defaults(fn=cmd_interrupt)

    s = sub.add_parser("rescue", help="hand a struggling task to another (default: stronger) worker in the same worktree")
    s.add_argument("task")
    s.add_argument("--to", help="worker name or model alias")
    s.add_argument("-m", "--message", help="diagnosis / guidance for the new worker")
    s.set_defaults(fn=cmd_rescue)

    s = sub.add_parser("consult", help="ask a (reasoning) worker to diagnose a task read-only")
    s.add_argument("task")
    s.add_argument("-m", "--message", required=True)
    s.add_argument("--to")
    s.set_defaults(fn=cmd_consult)

    s = sub.add_parser("resume", help="reconcile after crash/restart; restart lost turns via dsh sessions")
    s.add_argument("-m", "--message")
    s.add_argument("--respawn-idle", action="store_true", help="also recreate panes for dead idle workers")
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("note", help="append an orchestrator note to the todo board")
    s.add_argument("text")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("log", help="show a worker's turn log (rendered) or live pane")
    s.add_argument("worker")
    s.add_argument("--turn", type=int)
    s.add_argument("--lines", type=int, default=60)
    s.add_argument("--pane", action="store_true")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("events")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_events)

    s = sub.add_parser("gc", help="close run panes and remove finished worktrees")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_gc)

    s = sub.add_parser("_turn", help=argparse.SUPPRESS)
    s.add_argument("spec")
    s.set_defaults(fn=cmd_turn)
    return p


def main(argv=None):
    args = build().parse_args(argv)
    try:
        args.fn(args)
    except (herdr.HerdrError, gitops.GitError) as e:
        die(str(e))


if __name__ == "__main__":
    main()
