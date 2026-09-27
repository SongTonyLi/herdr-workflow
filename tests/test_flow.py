"""Integration tests: real hw CLI + real git, fake herdr panes + fake dsh."""
import json
import subprocess
import time


def add(env, tid, kind="implement", spec="do it", deps=(), files=(), verify=None, model=None):
    args = ["task", "add", tid, "--title", f"title {tid}", "--kind", kind, "--spec", spec]
    if deps:
        args += ["--deps", *deps]
    if files:
        args += ["--files", *files]
    if verify:
        args += ["--verify", verify]
    if model:
        args += ["--model", model]
    env.hw(*args)


def test_full_flow_with_deps_routing_and_merge(env):
    add(env, "design", kind="design", spec="write the design [[file DESIGN.md]]")
    add(env, "impl-a", deps=["design"], spec="[[file a.txt]]", files=["a.txt"], verify="test -f a.txt")
    add(env, "impl-b", deps=["design"], spec="[[file b.txt]]", files=["b.txt"])
    r = env.hwj("schedule", "--apply")
    assert [a["spawn"] for a in r["planned"]] == ["grok"]
    env.wait_all()
    s = env.state()
    assert s["tasks"]["design"]["status"] == "review"
    assert s["tasks"]["design"]["outcome"] == "completed/DONE"
    rv = env.hwj("review", "design")
    assert rv["commits_ahead"] == 1
    env.hwj("merge", "design")
    r = env.hwj("schedule", "--apply")
    assert sorted(a["spawn"] for a in r["planned"]) == ["composer", "flash"]
    env.wait_all()
    for t in ("impl-a", "impl-b"):
        env.hwj("merge", t)
    s = env.state()
    assert all(t["status"] == "done" for t in s["tasks"].values())
    files = subprocess.run(["git", "ls-files"], cwd=env.root, capture_output=True, text=True).stdout.split()
    assert {"DESIGN.md", "a.txt", "b.txt"} <= set(files)
    models = {c["model"] for c in env.dsh_calls()}
    assert models == {"grok-4.7-high", "composer-2.5-fast", "deepseek/deepseek-v4-flash-0731"}
    # impl tasks were told about the upstream design report
    prompt = (env.root / ".hw/tasks/impl-a").glob("prompt-*.md")
    assert "design (title design)" in next(prompt).read_text()
    todo = (env.root / ".hw/TODO.md").read_text()
    assert "Progress: 3/3 done" in todo


def test_blocked_then_steer_resumes_same_session(env):
    add(env, "t1", spec="[[block]] needs a decision")
    env.hwj("assign", "t1", "--to", "flash")
    env.wait_all()
    s = env.state()
    t = s["tasks"]["t1"]
    assert t["outcome"] == "completed/BLOCKED" and t["failures"] == 1
    sid = t["session"]["id"]
    env.hwj("steer", "t1", "-m", "Decision: use option A. HINT-OK")
    env.wait_all()
    calls = env.dsh_calls()
    assert calls[-1]["resumed"] and calls[-1]["session"] == sid
    assert env.state()["tasks"]["t1"]["outcome"] == "completed/DONE"


def test_failure_rescue_escalates_to_reasoning_model_in_same_worktree(env):
    add(env, "hard", spec="[[fail]] tricky")
    env.hwj("assign", "hard", "--to", "flash")
    env.wait_all()
    t = env.state()["tasks"]["hard"]
    assert t["outcome"].startswith("failed") and t["failures"] == 1
    r = env.hwj("rescue", "hard", "-m", "Root cause: X. HINT-OK")
    assert r["model"] == "grok"
    env.wait_all()
    calls = env.dsh_calls()
    assert calls[-1]["model"] == "grok-4.7-high" and not calls[-1]["resumed"]
    assert calls[-1]["cwd"].endswith("/.hw/wt/hard") and calls[0]["cwd"] == calls[-1]["cwd"]
    s = env.state()
    assert s["tasks"]["hard"]["worker"].startswith("grok") and s["tasks"]["hard"]["outcome"] == "completed/DONE"


def _wait_for(pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


def test_pane_killed_mid_turn_resumes_with_same_session(env):
    add(env, "slow", spec="[[sleep 30]] long job")
    r = env.hwj("assign", "slow", "--to", "composer")
    assert _wait_for(lambda: len(env.dsh_calls()) == 1)
    sid = env.dsh_calls()[0]["session"]
    subprocess.run([env.env["HW_HERDR_BIN"], "pane", "close", r["pane"]], env=env.env, check=True, capture_output=True)
    w = env.hwj("wait", "--interval", "0.3", "--timeout", "20")
    types = {e["event"] for e in w["events"]}
    assert "worker_dead" in types
    s = env.state()
    assert s["tasks"]["slow"]["interrupted"] is True and s["tasks"]["slow"]["failures"] == 0
    res = env.hwj("resume")
    assert res["resumed"][0]["session"] == sid and res["respawned"] == [r["worker"]]
    env.wait_all()
    calls = env.dsh_calls()
    assert calls[-1]["resumed"] and calls[-1]["session"] == sid
    s = env.state()
    assert s["tasks"]["slow"]["outcome"] == "completed/DONE"
    assert s["workers"][r["worker"]]["pane_id"] != r["pane"]


def test_lost_runner_without_exit_file_is_resumed(env):
    add(env, "slow", spec="[[sleep 30]] long job")
    r = env.hwj("assign", "slow", "--to", "flash")
    assert _wait_for(lambda: len(env.dsh_calls()) == 1)
    pid = int((env.root / f".hw/logs/{r['worker']}/turn-1.pid").read_text())
    import os, signal
    os.killpg(os.getpgid(pid), signal.SIGKILL)  # no chance to write an exit file
    time.sleep(0.5)
    # age gate for "lost" is 20s; fake it by backdating the turn start
    sp = env.root / ".hw/state.json"
    s = json.loads(sp.read_text())
    s["workers"][r["worker"]]["current"]["started_at"] -= 60
    sp.write_text(json.dumps(s))
    res = env.hwj("resume")
    assert res["resumed"] and res["resumed"][0]["session"] == env.dsh_calls()[0]["session"]
    env.wait_all()
    assert env.state()["tasks"]["slow"]["outcome"] == "completed/DONE"


def test_steer_while_running_interrupts_then_resumes(env):
    add(env, "slow", spec="[[sleep 30]] long job")
    env.hwj("assign", "slow", "--to", "flash")
    assert _wait_for(lambda: len(env.dsh_calls()) == 1)
    sid = env.dsh_calls()[0]["session"]
    env.hwj("steer", "slow", "-m", "change of plan: do the short version")
    env.wait_all()
    calls = env.dsh_calls()
    assert calls[-1]["resumed"] and calls[-1]["session"] == sid
    assert env.state()["tasks"]["slow"]["outcome"] == "completed/DONE"


def test_merge_conflict_is_aborted_and_sent_back(env):
    add(env, "x", spec="[[file same.txt]]")
    add(env, "y", spec="[[file same.txt]]")
    env.hwj("schedule", "--apply")
    env.wait_all()
    env.hwj("merge", "x")
    p = env.hw("merge", "y", check=False)
    assert p.returncode == 3
    s = env.state()
    assert s["tasks"]["y"]["status"] == "review" and "conflict" in s["tasks"]["y"]["merge_error"]
    st = subprocess.run(["git", "status", "--porcelain"], cwd=env.root, capture_output=True, text=True).stdout
    assert st.strip() == ""  # base left clean


def test_post_merge_verify_failure_rolls_back(env):
    add(env, "v", spec="[[file v.txt]]", verify="test -f nope.txt")
    env.hwj("assign", "v")
    env.wait_all()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=env.root, capture_output=True, text=True).stdout
    p = env.hw("merge", "v", check=False)
    assert p.returncode == 3
    head2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=env.root, capture_output=True, text=True).stdout
    assert head == head2


def test_consult_is_read_only_and_does_not_steal_task(env):
    add(env, "b", spec="[[block]]")
    env.hwj("assign", "b", "--to", "composer")
    env.wait_all()
    r = env.hwj("consult", "b", "-m", "why blocked?")
    env.wait_all()
    s = env.state()
    assert s["tasks"]["b"]["worker"].startswith("composer")
    assert s["tasks"]["b"]["consults"][0]["ok"]
    assert "HINT-OK" in open(r["answer_file"]).read()
    assert s["workers"][r["worker"]]["model"] == "grok"


def test_escalation_after_two_failures_via_schedule(env):
    add(env, "f", spec="[[fail]]")
    env.hwj("assign", "f", "--to", "flash")
    env.wait_all()
    env.hwj("steer", "f", "-m", "try again [[fail]]", "--count-failure")
    env.wait_all()
    t = env.state()["tasks"]["f"]
    assert t["failures"] >= 2
    shown = env.hwj("task", "show", "f")
    assert shown["effective_tier"] == "reason"


def test_build_junk_is_never_merged(env):
    add(env, "j", spec="[[file j.txt]]")
    env.hwj("assign", "j")
    env.wait_all()
    wt = env.root / ".hw/wt/j"
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_bytes(b"junk")
    (wt / "real.txt").write_text("forgot to commit\n")
    env.hwj("merge", "j")
    files = subprocess.run(["git", "ls-files"], cwd=env.root, capture_output=True, text=True).stdout.split()
    assert "real.txt" in files and not any("pycache" in f for f in files)


def test_concurrent_waiters_both_see_turn_end(env):
    add(env, "w", spec="[[sleep 2]]")
    env.hwj("assign", "w")
    import sys
    from conftest import HW
    procs = [subprocess.Popen([sys.executable, str(HW), "wait", "--interval", "0.2", "--timeout", "30"],
                              cwd=env.root, env=env.env, stdout=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
    for o in outs:
        assert [e["event"] for e in o["events"]] == ["turn_end"] and o["needs_review"] == ["w"]
