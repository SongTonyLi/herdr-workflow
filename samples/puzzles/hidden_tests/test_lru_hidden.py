import pytest
from puzzles.lru import TTLCache
class Clock:
    t = 0.0
    def __call__(self): return self.t
def test_lru_and_ttl():
    c = Clock(); k = TTLCache(2, 10, clock=c)
    k.set("a", 1); k.set("b", 2); assert k.get("a") == 1
    k.set("c", 3)  # evicts b (LRU)
    assert "b" not in k and k.get("a") == 1 and k.get("c") == 3
    c.t = 10; assert k.get("a") is None and len(k) == 0
def test_expired_evicted_before_lru():
    c = Clock(); k = TTLCache(2, 10, clock=c)
    k.set("old", 1); c.t = 5; k.set("new", 2); c.t = 11
    k.get("new"); k.set("x", 3)
    assert "new" in k and "x" in k and len(k) == 2
def test_update_refreshes():
    c = Clock(); k = TTLCache(2, 10, clock=c)
    k.set("a", 1); c.t = 8; k.set("a", 2); c.t = 15
    assert k.get("a") == 2
    assert k.delete("a") and not k.delete("a")
def test_purge_and_validation():
    c = Clock(); k = TTLCache(3, 1, clock=c)
    k.set(1, 1); k.set(2, 2); c.t = 1; k.set(3, 3)
    assert k.purge() == 2 and len(k) == 1
    with pytest.raises(ValueError): TTLCache(0, 1)
    with pytest.raises(ValueError): TTLCache(1, 0)
