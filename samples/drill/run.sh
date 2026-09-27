#!/usr/bin/env bash
# Failure drill. Creates the run only; the drill steps are driven by the orchestrator (see README.md).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HW="${HW:-$HOME/.claude/skills/herdr-orchestrator/bin/hw}"
T="$1"; mkdir -p "$T"; cp -R "$HERE/seed/." "$T/"; cd "$T"
git init -q; git add -A; git commit -qm "seed"
"$HW" init --goal "Failure drill: escalation, pane death, orchestrator restart" --run drill --max-workers 3
H="$HERE/../puzzles/hidden_tests"
"$HW" task add hardexpr --kind implement --title "Arithmetic evaluator given to a fast model" --spec-file "$HERE/specs/hardexpr.md" \
  --files puzzles/expr.py tests/test_expr.py \
  --verify "PYTHONPATH=. uvx --with pytest pytest -q -p no:cacheprovider tests/test_expr.py $H/test_expr_hidden.py"
"$HW" task add mdhtml --kind implement --title "Markdown to HTML (long turn, will be killed)" --spec-file "$HERE/specs/mdhtml.md" \
  --files puzzles/mdhtml.py tests/test_mdhtml.py --verify "uvx --with pytest pytest -q -p no:cacheprovider tests/test_mdhtml.py"
"$HW" todo
