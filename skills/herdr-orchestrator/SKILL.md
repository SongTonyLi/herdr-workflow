---
name: herdr-orchestrator
description: Orchestrate several dsh coding agents running in separate Herdr panes, each on its own git worktree, to build a project in parallel. Use when the user asks to orchestrate, delegate, or fan out a project or its subtasks to multiple coding agents/models via herdr (e.g. grok for reasoning, composer / deepseek flash for fast implementation), or to resume such a run. Persistent and resumable; requires HERDR_ENV=1.
---

# Herdr Orchestrator

You are the **orchestrator**. You do not write the project yourself. You decompose it, delegate subtasks to worker agents in Herdr panes, review and steer their work, rescue workers that struggle, merge results, and keep the todo board honest. The `hw` CLI handles all the mechanics (state, panes, dsh sessions, worktrees, merges). You handle the judgment.

```bash
HW=~/.claude/skills/herdr-orchestrator/bin/hw      # alias this; every command below is "$HW ..."
```

Preconditions: `test "$HERDR_ENV" = 1`. If that fails, stop and tell the user. `dsh` must be on PATH. Run every `hw` command from the project root, or set `HW_ROOT=<project>`.

## Model roster (models.json)

| alias | model | tier | use for |
|---|---|---|---|
| `grok` | cursor `grok-4.7-high` | reason | design, interfaces, tricky algorithms, debugging, review, diagnosing stuck workers |
| `composer` | cursor `composer-2.5-fast` | fast | implementing well-specified modules, tests |
| `flash` | openrouter `deepseek-v4-flash` | fast | boilerplate, tests, docs, simple modules |

Task `kind` → tier: `design|reason|debug|review` go to reason; `implement|test|docs|chore` go to fast. Pin a model with `--model`. After `escalate_after` failures (default 2), a fast task is automatically routed to the reason tier. You can change limits with `$HW config --set max_workers=5 --set models.grok.max_parallel=3`.

## Start or resume

1. **Check whether a run already exists**: `ls .hw/state.json`. If it does, this is a **resume**. Run `$HW resume`, then `$HW status`, read `.hw/TODO.md` and the last lines of `$HW events`, and continue the loop below. Do not re-create tasks.
2. **New run**: `$HW init --goal "<one-line goal>" [--max-workers N]`. This git-inits the project if needed and adds `.hw/` to `.git/info/exclude`.
3. **Plan the task graph.** Write specs that a fast model can execute without guessing:
   - Make a reasoning-heavy `design` task first when interfaces are unclear. Its output (e.g. `DESIGN.md`, stub signatures) gets merged and becomes the contract that implementers depend on.
   - Split implementation by **file ownership** (`--files`) so parallel branches rarely conflict. Put shared files (`__init__.py`, config, README) in one task, or leave them to yourself.
   - Give every task a **verify command** (`--verify "python -m pytest -q tests/test_x.py"`). It is run in the worktree during review and again on the base branch after merge.
   - Add `--deps` edges. Workers on dependent tasks get the upstream reports automatically.
   ```bash
   $HW task add design --kind design --title "Module interfaces" --spec-file /tmp/design.md --files DESIGN.md pkg/api.py
   $HW task add parser --kind implement --deps design --files pkg/parser.py tests/test_parser.py \
       --verify "python -m pytest -q tests/test_parser.py" --title "Parser" --spec "..."
   ```
4. Show the user the board (`$HW todo`) before spending model time if the plan is large or ambiguous.

## The control loop

Repeat until every task is `done`:

```bash
$HW schedule --apply          # starts ready tasks on idle workers; spawns panes up to limits; balances composer/flash
$HW wait --timeout 900        # blocks until some turn ends, stalls, or a pane dies (returns JSON events)
$HW status                    # reconciles and prints the TODO board
```

For each `turn_end` event, **review before merging**:

```bash
$HW review <task>             # runs verify in the worktree; shows result.md, diffstat, commits_ahead, last turn
$HW review <task> --diff      # when you need to read the code
```

Decide one of the following:
- **Accept**: `$HW merge <task>`. The merge is serialized under a lock, and verify runs again on base; if it fails there, the merge is rolled back. After a merge, run `$HW schedule --apply` again, since dependents may now be ready.
- **Needs changes**: `$HW steer <task> -m "<specific feedback: failing test output, the exact contract, the file to change>"`. This resumes the **same dsh session** in the same worktree, so the worker keeps its context. Add `--count-failure` if the attempt really failed; failures drive escalation.
- **Answer a question** from a `BLOCKED` report: `$HW steer <task> -m "<decision>"`.
- **Wrong direction or out of its depth**: follow the rescue ladder below.

`hw merge` exits with code 3 on a conflict or verify failure. The base is left clean, and the task returns to `review` with `merge_error`. Steer the worker with: `"Merge the latest <base> into your branch (git merge <base>), resolve the conflicts keeping both features, re-run verify, commit."`

Keep the loop tight. After `schedule --apply`, always `wait`. Never poll by reading panes in a busy loop. `$HW log <worker>` shows the rendered turn log, and `$HW log <worker> --pane` shows the live pane when you want to watch.

## Steering principles
- Feedback must be **concrete and verifiable**: paste the failing assertion, name the function, state the expected behavior. Vague "please fix" wastes a turn.
- Do not let workers edit outside their `--files` scope. If two tasks need the same file, add a dep between them or do the shared edit yourself on base, commit it, then tell the workers to `git merge <base>`.
- If you edit the base branch yourself, **commit before merging** (`hw merge` refuses a dirty base).
- Record decisions that affect several tasks with `$HW note "..."`. They appear on the board and survive restarts.

## Rescue ladder (when a worker fails, blocks, stalls, or loops)

Signals of trouble:
- the turn outcome is `failed/…`, `…/BLOCKED`, `…/PARTIAL`, or `(stale)` (no fresh report)
- verify fails twice
- a `stalled` event (the log hasn't grown in `stall_seconds`)
- the diff is going the wrong way

Escalate one step at a time:
1. **Steer** with precise feedback (above).
2. **Consult** a reasoning worker, read-only: `$HW consult <task> -m "Why does test_x fail? Give minimal fix steps."`. When it ends, read the `answer_file` and relay the key guidance with `$HW steer <task> -m "..."`. The struggling worker keeps ownership.
3. **Hand off**: `$HW rescue <task> [--to grok|composer|<worker>] -m "<diagnosis>"`. Without `--to`, it escalates to the next tier. The new worker continues in the **same worktree** with a handoff prompt containing the prior report, the diff, and the verify output.
4. **Do it yourself** as a last resort: edit in `.hw/wt/<task>`, commit on its branch, then `review` and `merge`.

Stalled but still working (the log is growing slowly)? Leave it alone. A stall with no log growth? Run `$HW steer <task> -m "Status check: summarize progress, then continue."`; this interrupts the turn and resumes it. `$HW interrupt <worker>` only stops a turn.

## Balancing and capacity
- `schedule` fills idle workers first, then spawns new panes while `max_workers` and each model's `max_parallel` allow. Among fast models it picks the least loaded, then alternates by history.
- Queue building up on one tier? Raise the limit (`hw config --set max_workers=6`) or re-kind a task. If the reason tier is the bottleneck, split design work so fast workers can start on the parts that are clear.
- Workers idling with nothing ready? Retire them with `$HW worker retire <name>` to free resources.
- To add a worker manually: `$HW worker spawn --model grok [--name reviewer]`.

## Robustness: races, crashes, resume
- **One writer**: only `hw` writes `.hw/state.json` (flock + atomic rename). Workers only write in their worktree and their `result.md`. Never edit state by hand.
- **Isolation**: each task has its own git worktree and branch (`hw/<task>`), and merges are serialized. Overlapping `--files` claims are never scheduled concurrently.
- **Panes outlive you**: if the orchestrator session dies, workers keep running. A new session runs `$HW resume`: running turns are left alone, finished ones are finalized, and turns killed with their pane (or whose runner vanished) are restarted **with the same dsh `--session-id` in the same worktree**, and the prompt tells the worker to check `git status` first. Crashes don't count as model failures.
- Stale evidence is ignored: each worker's turn numbers only go up, and a `result.md` older than the turn start is marked `(stale)`.
- Turn evidence lives in `.hw/logs/<worker>/turn-N.{json,jsonl,exit,pid}` and the audit trail in `.hw/events.jsonl`. Use them when you're unsure what happened.

## Finishing
1. When every task is `done`: run the full test suite on the base branch yourself. Then add a final `review`-kind task for grok if the change is large ("review the whole diff since <first commit> for bugs; report only actionable findings"). Act on its findings with new tasks.
2. `$HW gc` closes the run's panes and removes worktrees for finished tasks. It never touches panes it didn't create.
3. Report to the user: what was built, which model did what (`$HW events`), and any failures, rescues, and escalations.

## Gotchas
- A worker's final chat answer isn't visible to you except through `hw log`. Rely on `result.md` + verify + diff.
- Workers occasionally forget to commit. `merge` auto-commits worktree leftovers, but review them first (`review` shows `uncommitted`).
- dsh sessions are stored per working directory, so a session can only be resumed in the same worktree. `hw` handles this: sessions belong to (task, worker).
- Don't send prompts to worker panes with `herdr pane run` directly. Always go through `hw` so state and evidence stay consistent.
