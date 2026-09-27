Create `puzzles/expr.py` with `evaluate(src: str) -> int | float` — a safe arithmetic evaluator (NO eval/exec/ast.literal_eval/compile). Grammar:
- numbers: integers and decimals (`3`, `2.5`, `.5`); whitespace anywhere between tokens
- binary `+ - * / // %` with usual precedence, left-associative; `**` right-associative and binds tighter than unary minus on its left (`-2**2 == -4`, `2**-1 == 0.5`, `2**3**2 == 512`)
- unary `+`/`-` (repeatable: `--3 == 3`), parentheses
- `/` is true division; `//` and `%` follow Python semantics; integer results stay int when all operands are int (except `/`)
- errors: raise `ExprError(message, position)` (define it; subclass of ValueError, `.position` = 0-based char index of the offending token) for bad tokens, unbalanced parens, trailing input, empty input; division/modulo by zero raises `ExprError` too.
Write thorough tests in `tests/test_expr.py`. Think carefully about the precedence of `**` vs unary minus.
