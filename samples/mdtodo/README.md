# Sample 1: mdtodo (multi-module CLI)

Goal: a Python package `mdtodo` that manages TODO items stored in a Markdown checklist file.
Line format: `- [ ] Buy milk @due(2026-10-01) #home #errand` (`[x]` = done).

The seed (`seed/`) has only a pyproject. `run.sh` creates the run in `$E2E/mdtodo` and adds the task graph:

design (grok) ──┬─> parser (fast)  ──┐
                ├─> query  (fast)  ──┼─> cli (fast) ─> review (grok)
                └─> storage(fast)  ──┘
