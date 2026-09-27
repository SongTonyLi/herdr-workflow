Create `puzzles/intervals.py` with:
- `merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]`: merge overlapping or touching closed intervals ([1,3] and [3,5] -> [1,5]; [1,2] and [3,4] stay separate). Input may be unsorted; output sorted. Raise ValueError if any start > end.
- `insert(intervals, new) -> list[tuple[int,int]]`: insert into an already merged sorted list and return merged result.
Add tests in `tests/test_intervals.py`.
