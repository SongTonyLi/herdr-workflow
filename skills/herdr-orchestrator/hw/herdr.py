"""Thin wrapper over the `herdr` CLI. Every ID is read back from JSON, never guessed."""

from __future__ import annotations

import json
import os
import subprocess


class HerdrError(RuntimeError):
    pass


def _bin() -> str:
    return os.environ.get("HW_HERDR_BIN", "herdr")


def call(*args: str, check: bool = True) -> dict:
    proc = subprocess.run([_bin(), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        if not check:
            return {"error": (proc.stderr or proc.stdout).strip()}
        raise HerdrError(f"herdr {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"text": out}


def in_herdr() -> bool:
    return os.environ.get("HERDR_ENV") == "1"


def create_tab(workspace: str, cwd: str, label: str) -> tuple[str, str]:
    r = call("tab", "create", "--workspace", workspace, "--cwd", cwd, "--label", label, "--no-focus")
    res = r["result"]
    return res["tab"]["tab_id"], res["root_pane"]["pane_id"]


def tab_exists(tab_id: str) -> bool:
    r = call("tab", "get", tab_id, check=False)
    return "error" not in r


def layout(pane_id: str) -> dict:
    return call("pane", "layout", "--pane", pane_id)["result"]["layout"]


def split(pane_id: str, direction: str, cwd: str) -> str:
    r = call("pane", "split", pane_id, "--direction", direction, "--cwd", cwd, "--no-focus")
    return r["result"]["pane"]["pane_id"]


def split_largest(any_pane_in_tab: str, cwd: str) -> str:
    """Split the largest pane of a tab along its longer visual axis (cells are ~2:1)."""
    lay = layout(any_pane_in_tab)
    panes = lay["panes"]
    big = max(panes, key=lambda p: p["rect"]["width"] * p["rect"]["height"])
    r = big["rect"]
    direction = "right" if r["width"] >= 2 * r["height"] else "down"
    return split(big["pane_id"], direction, cwd)


def pane_get(pane_id: str) -> dict | None:
    r = call("pane", "get", pane_id, check=False)
    if "error" in r:
        return None
    return r.get("result", {}).get("pane")


def pane_alive(pane_id: str | None) -> bool:
    return bool(pane_id) and pane_get(pane_id) is not None


def foreground(pane_id: str) -> list[dict]:
    r = call("pane", "process-info", "--pane", pane_id, check=False)
    return r.get("result", {}).get("process_info", {}).get("foreground_processes", []) if "error" not in r else []


def rename(pane_id: str, label: str) -> None:
    call("pane", "rename", pane_id, label, check=False)


def run(pane_id: str, command: str) -> None:
    call("pane", "run", pane_id, command)


def send_keys(pane_id: str, *keys: str) -> None:
    call("pane", "send-keys", pane_id, *keys)


def read(pane_id: str, lines: int = 80) -> str:
    r = call("pane", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines), check=False)
    if "error" in r:
        return ""
    res = r.get("result", {})
    return res.get("text") or res.get("content") or r.get("text") or json.dumps(res)


def close(pane_id: str) -> None:
    call("pane", "close", pane_id, check=False)
