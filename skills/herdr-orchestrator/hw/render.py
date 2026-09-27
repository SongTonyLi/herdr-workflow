"""Render a human-readable TODO.md from state."""

from __future__ import annotations

import time

from . import sched


def _age(ts: float | None) -> str:
    if not ts:
        return ""
    s = int(time.time() - ts)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    return f"{s // 3600}h"


def todo_markdown(state: dict) -> str:
    tasks = sorted(state["tasks"].values(), key=lambda t: t["seq"])
    workers = state["workers"]
    ready_ids = {t["id"] for t in sched.ready_tasks(state)}

    def line(t: dict, box: str) -> str:
        bits = [f"- [{box}] **{t['id']}** {t['title']}", f"`{t.get('kind', '?')}`"]
        tier = sched.tier_for(t, state["config"])
        bits.append(f"tier={tier}")
        if t.get("worker"):
            w = workers.get(t["worker"], {})
            bits.append(f"@{t['worker']}({w.get('model', '?')})")
        if t.get("deps"):
            bits.append("deps=" + ",".join(t["deps"]))
        if t.get("attempts"):
            bits.append(f"attempts={t['attempts']}")
        if t.get("failures"):
            bits.append(f"failures={t['failures']}")
        if t.get("outcome"):
            bits.append(f"last={t['outcome']}")
        if t["status"] in ("running", "review"):
            bits.append(_age(t.get("status_at")))
        s = " · ".join(b for b in bits if b)
        if t.get("note"):
            s += f"\n  - note: {t['note']}"
        return s

    groups = [
        ("Running", [t for t in tasks if t["status"] == "running"], "~"),
        ("Needs review / decision", [t for t in tasks if t["status"] == "review"], "?"),
        ("Ready", [t for t in tasks if t["id"] in ready_ids], " "),
        ("Waiting on deps", [t for t in tasks if t["status"] == "todo" and t["id"] not in ready_ids], " "),
        ("Done", [t for t in tasks if t["status"] == "done"], "x"),
        ("Cancelled", [t for t in tasks if t["status"] == "cancelled"], "-"),
    ]
    out = [f"# TODO — run `{state['run']}`", "", f"Goal: {state['goal']}", ""]
    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] == "done")
    out.append(f"Progress: {done}/{total} done")
    out.append("")
    for title, items, box in groups:
        if not items:
            continue
        out.append(f"## {title} ({len(items)})")
        out.extend(line(t, box) for t in items)
        out.append("")
    out.append("## Workers")
    if not workers:
        out.append("- (none)")
    for w in sorted(workers.values(), key=lambda w: w["seq"]):
        cur = w.get("current") or {}
        what = f"{cur.get('kind', '')}:{cur.get('task', '')} turn {cur.get('turn', '')}" if cur else "-"
        out.append(
            f"- {w['name']} · {w['model']} · {w['status']} · pane={w.get('pane_id')} · {what}"
        )
    if state.get("notes"):
        out += ["", "## Orchestrator notes"]
        out += [f"- {n['text']}" for n in state["notes"][-15:]]
    return "\n".join(out) + "\n"


def write_todo(store, state: dict) -> None:
    (store.dir / "TODO.md").write_text(todo_markdown(state))
