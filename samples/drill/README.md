# Sample 3: failure drill

1. **Escalation**: `hw assign hardexpr --to flash`. The hidden tests are strict (error positions, `-2**2`, int/float types). If flash fails verify, the orchestrator walks the rescue ladder:
   - steer with the failing assertions (`--count-failure`)
   - `consult` grok, then relay its answer
   - `rescue` (auto-escalates to grok)
2. **Pane death**: `hw assign mdhtml --to composer`. Once its dsh session has started, close its pane with `herdr pane close <pane>`. `hw wait` reports `worker_dead`. `hw resume` respawns the pane and resumes the **same dsh session** in the same worktree.
3. **Orchestrator restart**: start a *fresh* Claude Code agent in a new herdr pane in the run directory and ask it to resume the run with the herdr-orchestrator skill and finish it. It runs `hw resume` / `status` and completes the loop without any context from the original session.
