from hw import sched
from hw.cli import load_models


def mkstate(tasks=(), workers=(), max_workers=4):
    cfg = load_models()
    cfg["max_workers"] = max_workers
    s = {"config": cfg, "tasks": {}, "workers": {}, "stats": {}}
    for i, t in enumerate(tasks):
        s["tasks"][t["id"]] = {"seq": i, "status": "todo", "deps": [], "kind": "implement", **t}
    for i, w in enumerate(workers):
        s["workers"][w["name"]] = {"seq": i, "status": "idle", **w}
    return s


def test_tier_routing_and_escalation():
    cfg = load_models()
    assert sched.tier_for({"kind": "design"}, cfg) == "reason"
    assert sched.tier_for({"kind": "implement"}, cfg) == "fast"
    assert sched.tier_for({"kind": "implement", "failures": 1}, cfg) == "fast"
    assert sched.tier_for({"kind": "implement", "failures": 2}, cfg) == "reason"
    assert sched.tier_for({"kind": "implement", "model": "grok"}, cfg) == "reason"
    assert sched.candidates({"kind": "review"}, cfg) == ["grok"]
    assert set(sched.candidates({"kind": "test"}, cfg)) == {"composer", "flash"}


def test_deps_gate_readiness():
    s = mkstate([{"id": "a"}, {"id": "b", "deps": ["a"]}])
    assert [t["id"] for t in sched.ready_tasks(s)] == ["a"]
    s["tasks"]["a"]["status"] = "done"
    assert [t["id"] for t in sched.ready_tasks(s)] == ["b"]


def test_plan_spawns_balanced_fast_workers_and_grok_for_reasoning():
    s = mkstate([{"id": "d", "kind": "design"}, {"id": "i1"}, {"id": "i2"}, {"id": "i3"}])
    acts = sched.plan(s)
    spawned = [a["spawn"] for a in acts]
    assert spawned[0] == "grok"
    assert sorted(spawned[1:3]) == ["composer", "flash"]  # alternates across fast models
    assert len(acts) == 4


def test_plan_respects_max_workers_and_prefers_idle():
    s = mkstate([{"id": "i1"}, {"id": "i2"}, {"id": "i3"}],
                [{"name": "flash-1", "model": "flash"}], max_workers=2)
    acts = sched.plan(s)
    assert acts[0] == {"task": "i1", "worker": "flash-1"}
    assert acts[1] == {"task": "i2", "spawn": "composer"}
    assert len(acts) == 2


def test_plan_serializes_overlapping_files():
    s = mkstate([{"id": "a", "files": ["src/x.py"]}, {"id": "b", "files": ["src/"]}, {"id": "c", "files": ["docs/*"]}])
    ids = [a["task"] for a in sched.plan(s)]
    assert ids == ["a", "c"]


def test_files_overlap():
    assert sched.files_overlap(["src/a.py"], ["src/*.py"])
    assert sched.files_overlap(["src"], ["src/a/b.py"])
    assert not sched.files_overlap(["src/a.py"], ["tests/a.py"])
