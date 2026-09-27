import sys, time, pytest
from puzzles.match import match
@pytest.mark.parametrize("p,t,exp", [
    ("abc", "abc", True), ("abc", "abcd", False), ("a.c", "abc", True), ("a*", "", True),
    ("a+", "", False), ("a+b", "aaab", True), ("colou?r", "color", True), ("colou?r", "colour", True),
    ("[a-c]+", "abcab", True), ("[a-c]+", "abd", False), ("[^0-9]*", "abc", True), ("[^0-9]*", "a1", False),
    (r"a\.b", "a.b", True), (r"a\.b", "axb", False), (r"\*+", "***", True), (r"a\\", "a\\", True),
    (".*x.*", "abxcd", True), ("[a-z0-9]?z", "9z", True), ("[a-]x", "-x", True),
])
def test_cases(p, t, exp):
    assert match(p, t) is exp
@pytest.mark.parametrize("p", ["*a", "a\\", "[abc", "+"])
def test_invalid(p):
    with pytest.raises(ValueError):
        match(p, "a")
def test_no_re():
    import puzzles.match as m
    src = open(m.__file__).read()
    assert "import re" not in src and "fnmatch" not in src
def test_polynomial():
    t = time.time()
    assert match("a*" * 20 + "b", "a" * 40) is False
    assert time.time() - t < 2
