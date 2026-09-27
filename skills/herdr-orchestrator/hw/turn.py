"""In-pane turn runner: executes one dsh headless turn and leaves durable evidence.

Invoked inside a worker pane as `hw _turn <spec.json>`. It never touches state.json;
the orchestrator reconciles from these files:

  turn-N.pid    written at start (pid of this runner)
  turn-N.jsonl  raw dsh --json events
  turn-N.exit   JSON {rc, status, session_id, final, error, ended_at} written last
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"


def _short(v, n=160) -> str:
    s = v if isinstance(v, str) else json.dumps(v)
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _describe_tool(ev: dict) -> str:
    inp = ev.get("input") or {}
    for key in ("command", "file_path", "path", "pattern", "query", "url"):
        if key in inp:
            return f"{ev.get('tool')} {_short(inp[key], 120)}"
    return f"{ev.get('tool')} {_short(inp, 120)}"


def render_event(ev: dict) -> str | None:
    t = ev.get("type")
    if t == "session":
        return f"{DIM}session {ev.get('sessionId')} cwd={ev.get('cwd')}{RESET}"
    if t == "thinking":
        return f"{DIM}… {_short(ev.get('text', ''), 200)}{RESET}"
    if t == "text":
        return ev.get("text", "")
    if t == "tool_call":
        return f"{CYAN}→ {_describe_tool(ev)}{RESET}"
    if t == "tool_result":
        st = ev.get("status")
        col = GREEN if st == "completed" else RED
        return f"{col}  ← {st}{RESET} {DIM}{_short(ev.get('result', ''), 140)}{RESET}"
    if t == "final":
        return f"{BOLD}── final ──{RESET}\n{ev.get('text', '')}"
    if t in ("error",):
        return f"{RED}error: {_short(ev, 400)}{RESET}"
    if t == "status" and ev.get("phase") == "turn_end":
        return f"{DIM}turn_end {json.dumps(ev.get('reason'))}{RESET}"
    return None


def run(spec_path: str) -> int:
    spec_file = Path(spec_path)
    spec = json.loads(spec_file.read_text())
    base = spec_file.with_suffix("")  # .../turn-N
    pid_file = Path(f"{base}.pid")
    log_file = Path(f"{base}.jsonl")
    exit_file = Path(f"{base}.exit")
    if exit_file.exists():
        print(f"hw: {exit_file} already exists; refusing to rerun a finished turn", file=sys.stderr)
        return 2

    pid_file.write_text(str(os.getpid()))
    cmd = [spec.get("dsh_bin") or os.environ.get("HW_DSH_BIN", "dsh"), "--profile", spec.get("profile", "headless")]
    if spec.get("patch"):
        cmd += ["--patch", spec["patch"]]
    cmd += ["--json"]
    if spec.get("session_id"):
        cmd += ["--session-id", spec["session_id"]]
    cmd += ["-"]  # task text from stdin: avoids argv length/quoting issues

    print(f"{BOLD}[hw] {spec.get('worker')} · {spec.get('model')} · {spec.get('kind')}:{spec.get('task')} · turn {spec.get('turn')}{RESET}")
    print(f"{DIM}cwd={spec['cwd']}  resume={'yes ' + spec['session_id'] if spec.get('session_id') else 'no'}{RESET}")

    result = {"rc": None, "status": "failed", "session_id": spec.get("session_id"), "final": None, "error": None}
    child: subprocess.Popen | None = None
    killed = {"sig": None}

    def on_term(signum, _frame):
        killed["sig"] = signum
        if child and child.poll() is None:
            child.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGHUP, on_term)

    started = time.time()
    try:
        prompt = Path(spec["prompt_file"]).read_text()
        child = subprocess.Popen(
            cmd,
            cwd=spec["cwd"],
            env={**os.environ, **(spec.get("env") or {})},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # let diagnostics show in the pane
            text=True,
            bufsize=1,
        )
        assert child.stdin and child.stdout
        child.stdin.write(prompt)
        child.stdin.close()
        with open(log_file, "a") as log:
            for line in child.stdout:
                log.write(line)
                log.flush()
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    print(line, end="")
                    continue
                if ev.get("type") == "session" and ev.get("sessionId"):
                    result["session_id"] = ev["sessionId"]
                if ev.get("type") == "final":
                    result["final"] = ev.get("text")
                if ev.get("type") == "error":
                    result["error"] = _short(ev, 1000)
                if ev.get("type") == "status" and ev.get("phase") == "turn_end":
                    reason = (ev.get("reason") or {}).get("kind")
                    if reason and reason != "completed":
                        result["error"] = result["error"] or f"turn_end reason={reason}"
                out = render_event(ev)
                if out:
                    print(out, flush=True)
        rc = child.wait()
        result["rc"] = rc
        if killed["sig"]:
            result["status"] = "killed"
        elif rc == 0 and result["final"] is not None and not result["error"]:
            result["status"] = "completed"
        elif rc in (130, -2):
            result["status"] = "interrupted"
        else:
            result["status"] = "failed"
    except KeyboardInterrupt:
        if child and child.poll() is None:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
        result["rc"] = 130
        result["status"] = "interrupted"
    except Exception as e:  # noqa: BLE001 - record anything that goes wrong
        result["error"] = f"runner error: {e!r}"
        result["status"] = "failed"
    finally:
        result["ended_at"] = round(time.time(), 3)
        result["duration_s"] = round(time.time() - started, 1)
        tmp = Path(f"{exit_file}.tmp")
        tmp.write_text(json.dumps(result, indent=2))
        os.replace(tmp, exit_file)
        col = GREEN if result["status"] == "completed" else RED
        print(f"{col}HW_TURN_DONE {spec.get('worker')} {spec.get('turn')} status={result['status']} rc={result['rc']}{RESET}", flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
