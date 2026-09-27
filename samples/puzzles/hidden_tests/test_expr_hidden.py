import pytest
from puzzles.expr import evaluate, ExprError
@pytest.mark.parametrize("src,val", [
    ("1+2*3", 7), ("(1+2)*3", 9), ("7//2", 3), ("-7//2", -4), ("7%-3", -2), ("7/2", 3.5),
    ("2**3**2", 512), ("-2**2", -4), ("(-2)**2", 4), ("2**-1", 0.5), ("--3", 3), ("-+-3", 3),
    (" .5 + 1.5 ", 2.0), ("10-4-3", 3), ("2*3%4", 2), ("100/10/5", 2.0), ("1 - -1", 2),
])
def test_values(src, val):
    r = evaluate(src)
    assert r == val and type(r) is type(val)
@pytest.mark.parametrize("src,pos", [("1 + $", 4), ("(1+2", 4), ("1+2)", 3), ("", 0), ("1 2", 2)])
def test_errors(src, pos):
    with pytest.raises(ExprError) as e:
        evaluate(src)
    assert isinstance(e.value, ValueError)
    assert e.value.position == pos
def test_div_zero():
    for s in ("1/0", "1//0", "1%0"):
        with pytest.raises(ExprError):
            evaluate(s)
def test_no_eval(monkeypatch):
    import builtins
    monkeypatch.setattr(builtins, "eval", None)
    assert evaluate("2*(3+4)") == 14
