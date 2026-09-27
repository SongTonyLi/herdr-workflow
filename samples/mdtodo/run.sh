#!/usr/bin/env bash
# Create the mdtodo e2e run. Usage: run.sh <target-dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HW="${HW:-$HOME/.claude/skills/herdr-orchestrator/bin/hw}"
T="$1"; mkdir -p "$T"; cp -R "$HERE/seed/." "$T/"; cd "$T"
git init -q; git add -A; git commit -qm "seed"
"$HW" init --goal "Build mdtodo: a stdlib-only Python CLI managing TODO items in a Markdown checklist, with tests" --run mdtodo --max-workers 4
S="$HERE/specs"; V="uvx --with pytest pytest -q"
"$HW" task add design  --kind design    --title "Architecture + interfaces + model" --spec-file "$S/design.md" --files DESIGN.md mdtodo/ tests/test_model.py --verify "$V tests/test_model.py && python3 -c 'import mdtodo.parser, mdtodo.storage, mdtodo.query, mdtodo.cli'"
"$HW" task add parser  --kind implement --title "Markdown line parser"   --deps design --spec-file "$S/parser.md"  --files mdtodo/parser.py tests/test_parser.py   --verify "$V tests/test_parser.py"
"$HW" task add query   --kind implement --title "Filtering and sorting" --deps design --spec-file "$S/query.md"   --files mdtodo/query.py tests/test_query.py     --verify "$V tests/test_query.py"
"$HW" task add storage --kind implement --title "File storage"          --deps design --spec-file "$S/storage.md" --files mdtodo/storage.py tests/test_storage.py --verify "$V tests/test_storage.py"
"$HW" task add cli     --kind implement --title "argparse CLI"          --deps parser query storage --spec-file "$S/cli.md" --files mdtodo/cli.py tests/test_cli.py --verify "$V"
"$HW" task add review  --kind review    --title "Whole-package review"  --deps cli --spec-file "$S/review.md" --verify "$V"
"$HW" todo
