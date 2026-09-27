Create `puzzles/mdhtml.py` with `render(md: str) -> str`, a small Markdown-to-HTML converter (stdlib only, no markdown libs):
- ATX headings `#`..`######` -> `<h1>`..`<h6>`
- paragraphs (consecutive non-blank lines joined with a space) -> `<p>`
- unordered lists (`- ` or `* ` items, consecutive) -> `<ul><li>..</li></ul>`; ordered lists (`1. `) -> `<ol>`
- fenced code blocks ``` ... ``` -> `<pre><code>` with HTML-escaped content, no inline processing inside
- inline: `**bold**` -> `<strong>`, `*em*` -> `<em>`, `` `code` `` -> `<code>` (escaped, no nested formatting), `[text](url)` -> `<a href="url">text</a>`
- HTML-escape `& < > "` in text. Blocks joined with "\n".
Write thorough tests in `tests/test_mdhtml.py` (at least 15 cases) and make them pass.
