import pytest
from puzzles.intervals import merge, insert
def test_merge():
    assert merge([]) == []
    assert merge([(5, 6), (1, 3), (2, 4)]) == [(1, 4), (5, 6)]
    assert merge([(1, 3), (3, 5)]) == [(1, 5)]
    assert merge([(1, 2), (3, 4)]) == [(1, 2), (3, 4)]
    assert merge([(1, 10), (2, 3)]) == [(1, 10)]
    with pytest.raises(ValueError):
        merge([(3, 1)])
def test_insert():
    assert insert([(1, 2), (6, 9)], (3, 5)) == [(1, 2), (3, 5), (6, 9)]
    assert insert([(1, 2), (3, 5), (6, 7), (8, 10)], (4, 8)) == [(1, 2), (3, 10)]
    assert insert([], (1, 1)) == [(1, 1)]
