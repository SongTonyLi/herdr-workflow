"""Pure scheduling logic: readiness, tier routing, load balancing, conflict avoidance.

Nothing here touches disk or herdr, so it is fully unit-testable.
"""

from __future__ import annotations

from fnmatch import fnmatch

ACTIVE_WORKER = ("idle", "running")


def tier_for(task: dict, cfg: dict) -> str:
    """Tier a task should run on, escalating fast-tier tasks after repeated failures."""
    if task.get("model"):
        return cfg["models"][task["model"]]["tier"]
    tier = task.get("tier") or cfg["kind_tier"].get(task.get("kind", "implement"), "fast")
    order = cfg.get("tier_order", ["fast", "reason"])
    fails = task.get("failures", 0)
    esc = cfg.get("escalate_after", 2)
    if esc and fails >= esc and tier in order:
        idx = min(order.index(tier) + fails // esc, len(order) - 1)
        tier = order[idx]
    return tier


def candidates(task: dict, cfg: dict) -> list[str]:
    if task.get("model"):
        return [task["model"]]
    tier = tier_for(task, cfg)
    return [a for a, m in cfg["models"].items() if m["tier"] == tier]


def deps_done(task: dict, tasks: dict) -> bool:
    return all(tasks.get(d, {}).get("status") == "done" for d in task.get("deps", []))


def ready_tasks(state: dict) -> list[dict]:
    tasks = state["tasks"]
    out = [t for t in tasks.values() if t["status"] == "todo" and deps_done(t, tasks)]
    return sorted(out, key=lambda t: (-t.get("priority", 0), t["seq"]))


def blocked_tasks(state: dict) -> list[dict]:
    tasks = state["tasks"]
    return [t for t in tasks.values() if t["status"] == "todo" and not deps_done(t, tasks)]


def _norm(p: str) -> str:
    return p.rstrip("/")


def files_overlap(a: list[str], b: list[str]) -> bool:
    """Conservative overlap test between two lists of paths/globs."""
    for x in a or []:
        for y in b or []:
            x2, y2 = _norm(x), _norm(y)
            if x2 == y2 or fnmatch(x2, y2) or fnmatch(y2, x2):
                return True
            if x2.startswith(y2 + "/") or y2.startswith(x2 + "/"):
                return True
    return False


def load_by_alias(state: dict) -> dict[str, int]:
    load: dict[str, int] = {a: 0 for a in state["config"]["models"]}
    for w in state["workers"].values():
        if w["status"] == "running":
            load[w["model"]] = load.get(w["model"], 0) + 1
    return load


def plan(state: dict) -> list[dict]:
    """Return assignment actions for ready tasks.

    Each action is {"task": id, "worker": name} for an idle worker, or
    {"task": id, "spawn": alias} when a new worker should be created.
    """
    cfg = state["config"]
    workers = state["workers"]
    tasks = state["tasks"]
    load = load_by_alias(state)
    history = state.get("stats", {}).get("assigned", {})
    live = [w for w in workers.values() if w["status"] in ACTIVE_WORKER]
    idle = [w for w in live if w["status"] == "idle" and not w.get("reserved")]
    live_count = {a: 0 for a in cfg["models"]}
    for w in live:
        live_count[w["model"]] = live_count.get(w["model"], 0) + 1
    total_live = len(live)

    busy_files = [t.get("files", []) for t in tasks.values() if t["status"] in ("running", "review")]
    actions: list[dict] = []

    for task in ready_tasks(state):
        files = task.get("files", [])
        if files and any(files_overlap(files, bf) for bf in busy_files):
            continue
        cands = candidates(task, cfg)
        if not cands:
            continue
        # Prefer the least-loaded model, tie-broken by fewest historical assignments (alternation).
        rank = sorted(cands, key=lambda a: (load.get(a, 0), history.get(a, 0), a))
        chosen = None
        for alias in rank:
            w = next((w for w in idle if w["model"] == alias), None)
            if w:
                idle.remove(w)
                chosen = {"task": task["id"], "worker": w["name"]}
                break
        if not chosen:
            for alias in rank:
                cap = cfg["models"][alias].get("max_parallel", 1)
                if total_live < cfg.get("max_workers", 4) and live_count.get(alias, 0) < cap:
                    live_count[alias] = live_count.get(alias, 0) + 1
                    total_live += 1
                    chosen = {"task": task["id"], "spawn": alias}
                    break
        if chosen:
            alias = chosen.get("spawn") or workers[chosen["worker"]]["model"]
            load[alias] = load.get(alias, 0) + 1
            history = {**history, alias: history.get(alias, 0) + 1}
            busy_files.append(files)
            actions.append(chosen)
    return actions
