# herdr-workflow

A Claude Code skill, **`herdr-orchestrator`**, that turns a Claude session into an orchestrator of several
coding agents. Each worker runs in its own [Herdr](https://herdr.dev) pane as a `dsh` headless agent
on a chosen model, on its own git worktree.

- `skills/herdr-orchestrator/SKILL.md`: the orchestrator playbook (planning, control loop, steering, rescue ladder, resume).
- `skills/herdr-orchestrator/bin/hw`: stdlib-only Python CLI that does the mechanics:
  - durable state in `<project>/.hw/`, protected by flock and atomic writes
  - todo board (`.hw/TODO.md`)
  - pane lifecycle through `herdr`
  - dsh turns with session resume (`--session-id`)
  - per-task worktrees
  - serialized, verified merges with rollback
  - rescue/escalation, and crash recovery
- `skills/herdr-orchestrator/models.json`: model roster. `grok` is the reasoning tier; `composer` and `flash` are the fast tier.
- `tests/`: pytest suite using fake `herdr`/`dsh` stubs (`uvx --with pytest pytest -q tests/`).
- `samples/`: seed specs for the end-to-end runs. `docs/e2e-report.md` records the results.

Install: `ln -s "$PWD/skills/herdr-orchestrator" ~/.claude/skills/herdr-orchestrator`
