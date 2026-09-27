import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "herdr-orchestrator"
HW = SKILL / "bin" / "hw"
STUBS = Path(__file__).resolve().parent / "stubs"
sys.path.insert(0, str(SKILL))


class Env:
    def __init__(self, root: Path, fake: Path, env: dict):
        self.root, self.fake, self.env = root, fake, env

    def hw(self, *args, check=True):
        p = subprocess.run([sys.executable, str(HW), *args], cwd=self.root, env=self.env,
                           capture_output=True, text=True, timeout=120)
        if check and p.returncode != 0:
            raise AssertionError(f"hw {args} failed ({p.returncode}):\n{p.stdout}\n{p.stderr}")
        return p

    def hwj(self, *args, **kw):
        return json.loads(self.hw(*args, **kw).stdout)

    def state(self):
        return json.loads((self.root / ".hw" / "state.json").read_text())

    def dsh_calls(self):
        f = self.fake / "dsh.log"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def wait_all(self, timeout=60):
        return self.hwj("wait", "--all", "--interval", "0.3", "--timeout", str(timeout))


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    fake = tmp_path / "fake"
    e = dict(os.environ)
    e.update(
        HW_HERDR_BIN=str(STUBS / "herdr"),
        HW_DSH_BIN=str(STUBS / "dsh"),
        FAKE_HERDR_DIR=str(fake),
        HERDR_ENV="1",
        HERDR_WORKSPACE_ID="wT",
        HW_ROOT=str(root),
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
    )
    e.pop("HW_WORKSPACE", None)
    ev = Env(root, fake, e)
    ev.hw("init", "--goal", "test goal", "--run", "t", "--root", str(root))
    yield ev
    # kill any leftover fake pane processes
    sp = fake / "state.json"
    if sp.exists():
        for p in json.loads(sp.read_text())["panes"].values():
            if p.get("proc"):
                try:
                    os.killpg(p["proc"], 9)
                except OSError:
                    pass
