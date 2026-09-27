Design the architecture and public interfaces of the `mdtodo` package so that four other agents can implement modules IN PARALLEL without talking to each other. Your design is the contract.

Deliverables (create exactly these files):
1. `DESIGN.md` — data model, the exact Markdown line grammar (checkbox, text, `@due(YYYY-MM-DD)` optional, `#tags` zero or more, anything else is text; non-task lines like headings/blank lines must be preserved verbatim on save), task identity (1-based index among task lines in file order), error types, and per-module responsibilities + edge cases each implementer must handle.
2. `mdtodo/__init__.py` (version only) and `mdtodo/model.py` — FULLY implemented: `Task` dataclass (text: str, done: bool, due: datetime.date | None, tags: list[str], line_no: int | None) and error classes (`ParseError`, `TaskNotFound`).
3. Stub modules with final signatures, docstrings describing exact behavior, and bodies `raise NotImplementedError`:
   - `mdtodo/parser.py`: `parse_line(line) -> Task | None`, `format_task(task) -> str`, `parse_document(text) -> list[Task | str]` (tasks and verbatim non-task lines), `render_document(items) -> str`.
   - `mdtodo/storage.py`: `load(path) -> list[Task | str]`, `save(path, items)` (atomic write via temp file + os.replace), `add(path, task) -> int`, `complete(path, index)`, `remove(path, index)`; missing file = empty list.
   - `mdtodo/query.py`: `filter_tasks(tasks, *, done=None, tag=None, due_before=None) -> list[Task]`, `sort_tasks(tasks, key="due"|"text") -> list[Task]` (tasks without due sort last).
   - `mdtodo/cli.py`: `main(argv=None) -> int` with subcommands `add TEXT [--due D] [--tag T]...`, `list [--all] [--tag T] [--due-before D] [--sort due|text]`, `done N`, `rm N`, global `--file PATH` (default `TODO.md`). Output format for list: `{index:>3}. [x| ] text (due YYYY-MM-DD) #tag ...`.
4. `tests/test_model.py` with a few tests for model.py.

Do not implement parser/storage/query/cli bodies — other agents will. Make the docstrings precise enough that independent implementations will interoperate.
