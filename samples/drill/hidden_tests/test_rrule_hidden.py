"""Oracle tests: compare against python-dateutil over randomized rules."""
import datetime as dt
import random

import pytest
from dateutil.rrule import rrulestr

from puzzles.rrule import expand

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def oracle(rule, start):
    r = rrulestr(f"RRULE:{rule}", dtstart=dt.datetime.combine(start, dt.time()))
    return [d.date() for d in r]


def gen(rng):
    freq = rng.choice(["DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
    parts = [f"FREQ={freq}"]
    if rng.random() < 0.5:
        parts.append(f"INTERVAL={rng.randint(2, 3)}")
    has_multi_day = False
    if freq == "WEEKLY":
        if rng.random() < 0.7:
            ds = rng.sample(DAYS, rng.randint(1, 3))
            parts.append("BYDAY=" + ",".join(ds))
        if rng.random() < 0.3:
            parts.append("WKST=" + rng.choice(DAYS))
    if freq in ("MONTHLY", "YEARLY"):
        c = rng.random()
        if c < 0.35:
            ds = rng.sample(DAYS, rng.randint(1, 2))
            ords = [rng.choice(["", "1", "2", "-1", "-2", "3"]) for _ in ds]
            parts.append("BYDAY=" + ",".join(o + d for o, d in zip(ords, ds)))
        elif c < 0.6:
            parts.append("BYMONTHDAY=" + ",".join(map(str, rng.sample([1, 13, 15, 28, 29, 30, 31, -1, -2, -7], rng.randint(1, 2)))))
        elif c < 0.8:
            ds = rng.sample(DAYS[:5], rng.randint(2, 5))
            parts.append("BYDAY=" + ",".join(ds))
            parts.append("BYSETPOS=" + rng.choice(["1", "-1", "2", "1,-1"]))
            has_multi_day = True
    if freq in ("YEARLY", "DAILY", "MONTHLY") and rng.random() < 0.35:
        parts.append("BYMONTH=" + ",".join(map(str, sorted(rng.sample(range(1, 13), rng.randint(1, 3))))))
    if freq == "DAILY" and rng.random() < 0.3:
        parts.append("BYDAY=" + ",".join(rng.sample(DAYS, 2)))
    start = dt.date(2020, 1, 1) + dt.timedelta(days=rng.randint(0, 3650))
    until = start + dt.timedelta(days=rng.randint(30, 1500))
    parts.append("UNTIL=" + until.strftime("%Y%m%d"))
    return ";".join(parts), start


CASES = [gen(random.Random(i)) for i in range(300)]


@pytest.mark.parametrize("rule,start", CASES, ids=[f"{i}:{c[0]}@{c[1]}" for i, c in enumerate(CASES)])
def test_random_against_dateutil(rule, start):
    assert expand(rule, start) == oracle(rule, start)


@pytest.mark.parametrize("rule,start", [
    ("FREQ=MONTHLY;BYDAY=-1FR;COUNT=5", dt.date(2026, 1, 1)),
    ("FREQ=MONTHLY;BYMONTHDAY=31;COUNT=7", dt.date(2026, 1, 31)),
    ("FREQ=YEARLY;COUNT=4", dt.date(2024, 2, 29)),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=SU;COUNT=8", dt.date(2026, 3, 1)),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=MO;COUNT=8", dt.date(2026, 3, 1)),
    ("FREQ=YEARLY;BYDAY=20MO;COUNT=3", dt.date(2026, 1, 1)),
    ("FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU;COUNT=3", dt.date(2026, 1, 1)),
    ("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=6", dt.date(2026, 1, 1)),
    ("FREQ=DAILY;INTERVAL=10;COUNT=5", dt.date(2026, 12, 25)),
])
def test_known(rule, start):
    assert expand(rule, start) == oracle(rule, start)


def test_limit_without_count_or_until():
    assert len(expand("FREQ=DAILY", dt.date(2026, 1, 1), limit=17)) == 17


@pytest.mark.parametrize("bad", ["FREQ=HOURLY", "BYDAY=MO", "FREQ=DAILY;COUNT=2;UNTIL=20260101", "FREQ=DAILY;BYMONTH=13",
                                 "FREQ=DAILY;FOO=1", "FREQ=MONTHLY;BYMONTHDAY=0"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        expand(bad, dt.date(2026, 1, 1))


def test_stdlib_only():
    import puzzles.rrule as m
    src = open(m.__file__).read()
    assert "dateutil" not in src
