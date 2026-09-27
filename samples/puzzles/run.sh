#!/usr/bin/env bash
# Create the puzzles e2e run: 5 independent tasks, mixed difficulty, graded by hidden tests.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HW="${HW:-$HOME/.claude/skills/herdr-orchestrator/bin/hw}"
T="$1"; mkdir -p "$T"; cp -R "$HERE/seed/." "$T/"; cd "$T"
git init -q; git add -A; git commit -qm "seed"
"$HW" init --goal "Solve 5 independent algorithm puzzles as stdlib-only Python modules with tests" --run puzzles --max-workers 4
S="$HERE/specs"; H="$HERE/hidden_tests"
V() { echo "PYTHONPATH=. uvx --with pytest pytest -q -p no:cacheprovider tests/test_$1.py $H/test_$1_hidden.py"; }
"$HW" task add expr      --kind reason    --title "Safe arithmetic evaluator (precedence, **, errors)" --spec-file "$S/expr.md"      --files puzzles/expr.py tests/test_expr.py           --verify "$(V expr)"
"$HW" task add match     --kind reason    --title "Regex-lite matcher, polynomial time"               --spec-file "$S/glob.md"      --files puzzles/match.py tests/test_match.py         --verify "$(V match)"
"$HW" task add lru       --kind implement --title "LRU cache with TTL"                                 --spec-file "$S/lru.md"       --files puzzles/lru.py tests/test_lru.py             --verify "$(V lru)"
"$HW" task add intervals --kind implement --title "Interval merge/insert"                              --spec-file "$S/intervals.md" --files puzzles/intervals.py tests/test_intervals.py --verify "$(V intervals)"
"$HW" task add roman     --kind implement --title "Roman numerals (strict)"                            --spec-file "$S/roman.md"     --files puzzles/roman.py tests/test_roman.py         --verify "$(V roman)"
"$HW" todo
