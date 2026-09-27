import time, pytest
from puzzles.sudoku import solve, count_solutions, generate
HARD = [
    "8..........36......7..9.2...5...7.......457.....1...3...1....68..85...1..9....4..",
    "..............3.85..1.2.......5.7.....4...1...9.......5......73..2.1........4...9",
    "..53.....8......2..7..1.5..4....53...1..7...6..32...8..6.5....9..4....3......97..",
    "1....7.9..3..2...8..96..5....53..9...1..8...26....4...3......1..4......7..7...3..",
    "4.....8.5.3..........7......2.....6.....8.4......1.......6.3.7.5..2.....1.4......",
]
def valid(s):
    rows = [s[i*9:(i+1)*9] for i in range(9)]
    cols = ["".join(r[c] for r in rows) for c in range(9)]
    boxes = ["".join(rows[r][c] for r in range(br, br+3) for c in range(bc, bc+3)) for br in (0,3,6) for bc in (0,3,6)]
    return all(sorted(u) == list("123456789") for u in rows + cols + boxes)
@pytest.mark.parametrize("p", HARD)
def test_hard(p):
    t = time.time(); s = solve(p); dt = time.time() - t
    assert s and valid(s) and all(a in ".0" or a == b for a, b in zip(p, s)) and dt < 0.5
def test_invalid():
    for bad in ["1" * 80, "x" * 81, "11" + "." * 79]:
        with pytest.raises(ValueError):
            solve(bad)
def test_unsolvable():
    # consistent givens, but r1c9 must be 9 (row) while column 9 already has a 9
    assert solve("12345678." + "." * 27 + "........9" + "." * 36) is None
def test_count():
    assert count_solutions("." * 81, limit=5) == 5
    assert count_solutions(HARD[0]) == 1
def test_generate():
    for seed in (1, 2, 3):
        p = generate(seed, 26)
        assert p == generate(seed, 26)
        assert sum(ch not in ".0" for ch in p) == 26
        assert count_solutions(p, limit=2) == 1
    with pytest.raises(ValueError):
        generate(1, 16)
