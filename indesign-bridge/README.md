# InDesign bridge

Connection infrastructure that lets an agent reach Adobe InDesign. It is shared by the skills in this repository and holds no typography rules; those stay in each skill.

| Folder | What it is | Setup and usage |
| --- | --- | --- |
| `mcp/` | Local MCP server (Python, stdio) plus the UXP plugin it talks to through a private mailbox. Nine tools: inspection, guarded tracking edits, restore, explicit save. | [latin-book-typography/references/indesign-mcp.md](../latin-book-typography/references/indesign-mcp.md) |
| `uxp-dev/` | UXP development plugin for the UDT console: inspection and a verified close/open recipe. Not for routine use. | [latin-book-typography/references/indesign-uxp.md](../latin-book-typography/references/indesign-uxp.md) |

Install these once from a clone of the repository; they are not copied into a skills folder. The MCP server keeps its virtual environment, generated `plugin/config.js` and client fragments in `mcp/`, and its pairing state in the `--home` directory you pass to `setup.py`. Skills work without the bridge: the read-only and one-off JSX jobs ship inside each skill.

Tests, from `mcp/` with the requirements installed:

```sh
.venv/bin/python -m unittest discover -s tests -v
node tests/editor.test.cjs
```
