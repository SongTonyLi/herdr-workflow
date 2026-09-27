Create `puzzles/rrule.py` with:

    expand(rule: str, dtstart: datetime.date, limit: int = 2000) -> list[datetime.date]

which expands an iCalendar RRULE (RFC 5545) into the list of occurrence dates, **exactly matching python-dateutil's `rrule` semantics** — but WITHOUT importing dateutil or any third-party package (stdlib only; calendar/datetime are fine).

`rule` is the value after `RRULE:`, e.g. `FREQ=MONTHLY;INTERVAL=2;BYDAY=-1FR;UNTIL=20271231`. Supported parts:
- `FREQ` = DAILY | WEEKLY | MONTHLY | YEARLY (required)
- `INTERVAL` (default 1)
- `COUNT` or `UNTIL` (`YYYYMMDD`, inclusive) — at most one; if neither, stop at `limit` occurrences
- `BYMONTH` (1-12, comma list)
- `BYMONTHDAY` (1..31 and -31..-1, comma list; days that don't exist in a month are skipped, never clamped)
- `BYDAY` (comma list of `MO..SU`, optionally with a signed ordinal like `2TU`, `-1FR`; ordinals are relative to the month for MONTHLY, and to the year for YEARLY unless BYMONTH is given, in which case relative to the month)
- `BYSETPOS` (signed positions within each FREQ period's candidate set)
- `WKST` (default MO) — affects which days fall into a WEEKLY period when INTERVAL > 1

Semantics to get right (as dateutil does):
- DTSTART is the first occurrence only if it matches the rule; it is not added otherwise.
- When BYxxx parts are missing, defaults derive from DTSTART (e.g. MONTHLY with no BYDAY/BYMONTHDAY uses DTSTART's day of month; WEEKLY with no BYDAY uses DTSTART's weekday; YEARLY with no BY parts uses DTSTART's month and day).
- BYMONTHDAY and BYDAY together are an intersection (both must match).
- COUNT counts produced occurrences; UNTIL is inclusive.
- Invalid rules (unknown FREQ/part, bad values, both COUNT and UNTIL) raise ValueError.

This is a tricky, reasoning-heavy task: think through period expansion carefully (expand candidates per FREQ period, filter/expand by BY parts, apply BYSETPOS, then COUNT/UNTIL). Write tests in `tests/test_rrule.py`.
