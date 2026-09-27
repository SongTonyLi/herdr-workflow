import pytest
from puzzles.roman import to_roman, from_roman
def test_roundtrip():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n
    assert to_roman(1994) == "MCMXCIV" and to_roman(3999) == "MMMCMXCIX"
@pytest.mark.parametrize("bad", ["IIII", "VX", "IC", "MMMM", "", "iv", "XM", "VV", "IIV", "CMM"])
def test_reject(bad):
    with pytest.raises(ValueError):
        from_roman(bad)
@pytest.mark.parametrize("n", [0, 4000, -1])
def test_range(n):
    with pytest.raises(ValueError):
        to_roman(n)
