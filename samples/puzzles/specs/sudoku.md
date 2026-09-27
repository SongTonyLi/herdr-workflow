Create `puzzles/sudoku.py`:
- `solve(grid: str) -> str | None`: grid is 81 chars (`1-9` or `.`/`0` for blanks), row-major. Return the solved 81-digit string, or None if unsolvable. Raise ValueError for malformed input (wrong length/chars) or givens that already conflict.
- `count_solutions(grid: str, limit: int = 2) -> int`: number of solutions, stopping at `limit`.
- `generate(seed: int, clues: int = 28) -> str`: deterministic for a seed; returns a puzzle with a UNIQUE solution and exactly `clues` givens (or ValueError if clues < 17 or > 81).
Performance: each of the 10 hardest known puzzles (e.g. "Platinum Blonde", "Golden Nugget", AI Escargot) must solve in < 0.5 s in pure Python — use constraint propagation (naked/hidden singles) + MRV backtracking with bitmasks.
Tests in `tests/test_sudoku.py`.
