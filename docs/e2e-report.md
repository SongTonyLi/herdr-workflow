# End-to-end report — herdr-orchestrator

Date: 2026-09-26/27. Environment: herdr 0.9.1, dsh (headless profile).

Models:
- `grok` = cursor `grok-4.7-high` (reasoning tier)
- `composer` = cursor `composer-2.5-fast` (fast tier)
- `flash` = openrouter `deepseek-v4-flash-0731` (fast tier)

The orchestrator was this Claude Code session following `SKILL.md`, except drill (c), which used a fresh Claude session. Runs lived in `/tmp/hw-e2e/{mdtodo,puzzles,drill}`, each with its own herdr tab, and two runs executed at the same time.

The unit and integration suite (fake herdr/dsh, real git) is `uvx --with pytest pytest -q tests/`: **21 passed**.

## 1. mdtodo — multi-module CLI (6 tasks, dependency graph)

| task | kind → model | turns | result |
|---|---|---|---|
| design (DESIGN.md + model + stubs) | design → grok | 2 (steered) | DONE; the 269-line contract was used by all implementers |
| parser | implement → composer | 1 (35 s) | 39 tests |
| query | implement → flash | 1 (51 s) | 55 tests |
| storage | implement → composer | 1 (40 s) | 15 tests |
| cli | implement → flash | 1 (221 s) | merged, 140 tests |
| review (whole package) | review → grok | 1 (896 s) | added `__main__`; 142 tests |

- The three parallel tasks each ran in their own worktree with their own file ownership, and merged **with zero conflicts**.
- **Steering a struggling worker:** grok's design turn got stuck working around the dsh sandbox, which blocked `uvx`. I interrupted it and ran `hw steer` with the concrete fix. The worker resumed the **same dsh session** and finished in 81 s.
- **Orchestrator review found a gap:** `python -m mdtodo` did nothing. I added that finding to grok's review task, and grok fixed it with a test.
- Final: 142 tests pass on main; `python -m mdtodo --file x add "Ship it" --due 2026-10-02 --tag work` works.

## 2. puzzles — independent tasks, hidden tests, balancing (7 tasks)

- **Routing:** `schedule` sent `expr` and `match` (reason) to two grok panes, and `lru`, `intervals`, `roman` to composer/flash, alternating between them. With `max_workers=4`, `roman` queued until a worker was free, then went to the idle composer. Idle workers were retired.

| task | model | result (incl. hidden tests) |
|---|---|---|
| expr (safe evaluator) | grok | 214 passed |
| match (regex-lite, polynomial) | grok | 254 passed |
| lru (TTL cache) | composer | 11 passed |
| roman | composer | 29 passed |
| intervals | flash | 23 passed |
| sudoku (**consult → relay**) | flash (with grok's help) | 31 passed |
| topo (**rescue → escalate**) | flash → grok | 26 passed |

- **Rescue ladder step 2 (consult + relay).** I cut flash off mid-way on sudoku; it had an uncommitted draft and a crashing self-check. `hw consult` asked a grok worker to diagnose read-only. Grok found a real bug (`count_solutions` overshooting `limit`) and a `generate` determinism issue. It also found that **my hidden fixture was 80 chars**. I fixed the fixture rather than accept grok's suggested workaround, recorded an `hw note`, and relayed the rest with `hw steer`. Flash resumed its own session and passed.
- **Rescue ladder step 3 (handoff + escalation).** Flash was interrupted on `topo`. `hw rescue` with no target escalated to the reason tier and reused the idle `grok-6`, which continued in the **same worktree** from a handoff prompt. It passed with 26 tests.
- Final: 588 tests pass on main, visible and hidden.

## 3. drill — failure injection

1. **Fast model on hard tasks.**
   - flash was given `hardexpr` (strict evaluator; the hidden tests check error positions and int/float types) and passed 71/71.
   - It was then given `rrule`, an RRULE expander required to be dateutil-exact and checked against python-dateutil on 300 randomized rules. It passed **364/364** in one 944 s turn, and built its own dateutil comparison harness to get there.
   - So escalation never triggered naturally; flash was stronger than expected. Escalation was exercised live in puzzles (above) and deterministically in tests.
2. **Pane death mid-turn.**
   - I ran `herdr pane close` on composer's pane 39 s into `mdhtml`. The runner caught SIGHUP and wrote `killed` along with the session id.
   - `hw wait` reported `worker_dead`, and the task was marked `interrupted` with 0 failures, so the crash wasn't blamed on the model.
   - `hw resume` respawned the pane and resumed **the same dsh session** in the same worktree. The uncommitted work survived, and the task was DONE in 32 s.
3. **Orchestrator restart.**
   - I started a **fresh Claude Code session** (`herdr agent start orch2 --kind claude`) in the run directory with a one-paragraph instruction.
   - It loaded the skill, ran `hw resume` and `hw status`, reviewed and merged the pending `rrule`, ran the full suite (431 passed), ran `hw gc`, and wrote `ORCH2_REPORT.md`. It had no context from this session.

## Bugs found by the E2E and fixed (each with a regression test)

| symptom | fix |
|---|---|
| `merge` could auto-commit `__pycache__` | `init` writes common build/test junk to `.git/info/exclude` |
| dsh sandbox blocks `uvx`/`pip` caches, so workers burn turns | `worker_env` config points uv/pip caches at `$TMPDIR` (writable in the sandbox); the worker prompt explains the sandbox |
| concurrent `hw wait`/`status` callers swallowed each other's `turn_end` events | `wait` reads the durable `events.jsonl` since its start time and also reports `needs_review` and `ready` |
| `merge` right after a turn ended said "still running" | `review` and `merge` reconcile state first |
| an untracked `.claude-flow/` (plugin hook) blocked merges | the merge precondition only considers tracked changes |

## Observations
- **Latency:** fast models took 35–250 s per implementation task, and grok took 12–15 min per reasoning task. That's why balancing matters: fast tasks were merged while grok was still thinking.
- **Quality:** grok's design contract meant three fast workers could implement in parallel with no coordination and no conflicts.
- **Sandbox limits:** the dsh headless sandbox limits writes to the worktree, but `result.md` (outside it) was always writable.
- **Session scope:** dsh sessions are keyed by cwd, which is why `hw` scopes a session to (task, worker) and resumes only in the same worktree.
