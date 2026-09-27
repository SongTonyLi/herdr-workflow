Create `puzzles/lru.py` with class `TTLCache(capacity: int, ttl: float, clock=time.monotonic)`:
- `get(key, default=None)`: returns value if present and not expired (expired = now - set_time >= ttl), marks it most-recently-used; expired entries are removed on access.
- `set(key, value)`: insert/update (update refreshes TTL and recency); if over capacity, evict expired entries first, then the least-recently-used.
- `__len__` counts only non-expired entries; `__contains__` (no recency change); `delete(key) -> bool`; `purge() -> int` removes expired and returns how many.
- capacity < 1 or ttl <= 0 -> ValueError. O(1) average get/set (use OrderedDict).
Tests in `tests/test_lru.py` using a fake clock.
