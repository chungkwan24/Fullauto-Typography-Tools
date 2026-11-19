# Windows COM connection

Connect to an already-running Adobe InDesign on Windows through its registered COM server. This is shared connection infrastructure; typography rules and substantive layout payloads stay in the skill that requests them.

No UXP plugin, UXP Developer Tool or MCP server is required for this route. It is separate from the repository's UXP/MCP connection.

## Requirements

- Windows, installed InDesign, and Python 3.10 or later.
- `pywin32`, installed for the same Python interpreter that runs these scripts.
- Start InDesign yourself. The scripts refuse to connect when no matching running process can be identified.

From this directory, using your installed Python (the examples use the Windows `py` launcher):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `py` is unavailable, use the full path to an installed Python executable. A Windows Store placeholder named `python.exe` is not sufficient. No Adobe installation directory or version is configured in these scripts.

## 1. Discover the installation and running process

```powershell
.\.venv\Scripts\python.exe indesign_com.py discover
```

This reads both registry views and lists COM registrations and running InDesign processes. It does not activate COM or modify documents.

The connection selects a version-specific ProgID whose registered executable matches the running process. It never selects the unversioned `InDesign.Application` alias. Registry command-line arguments and quoted executable paths are handled separately.

If distinct versions are running, use `--pid` to select the intended process. Two processes using the same installed executable remain ambiguous even with `--pid`; COM registration alone cannot identify which one to use.

## 2. Verify a read-only connection

```powershell
.\.venv\Scripts\python.exe indesign_com.py probe
```

An optional `--output new-report.json` writes a new report without overwriting an existing file. With multiple distinct running versions, add `--pid` using a PID returned by discovery.

The probe:

1. Identifies the running executable and its unique version-specific registration.
2. Attaches with `GetActiveObject`; if unavailable, tries that version's local COM server only after the running-process check.
3. Rechecks process identity and rejects an unexpected extra instance of that executable.
4. Resolves JavaScript's ScriptLanguage value from the installed type library, rather than hardcoding a numeric constant.
5. Runs a scalar read-only `DoScript` expression and compares document IDs, names, page counts and modified flags before and after.

A successful probe proves connection and this read-only expression, not a whole-book typography pass or every InDesign operation. It does not create, save, close or reopen a document. The process check is conservative: if COM starts an unexpected instance, the script reports the failure and does not close it automatically.

## 3. Execute an explicitly authorized payload

Use `run_jsx.py` only when the user has authorized the payload's operations. Obtain the current document ID and exact name from the probe; do not reuse IDs from another application session.

The payload is a self-contained ES3 expression evaluating to `function(doc, job, helpers)`. Its return value must be JSON-compatible. Preprocessor directives and automatic include rewriting are not supported.

A read-only payload can be as small as:

```javascript
(function (doc, job, helpers) {
    return {id: doc.id, name: doc.name, pages: doc.pages.length};
})
```

Run it using the ID and name from your own probe:

```powershell
.\.venv\Scripts\python.exe run_jsx.py .\inspect.jsx --document-id 7 --document-name "Example.indd" --job-dir .\jobs\inspect-001
```

The ID, filename and job directory above are examples. A fresh job directory is mandatory. The executor snapshots the payload and records `PREPARED`, `RUNNING`, then `COMPLETE`, `FAILED` or `UNKNOWN` in `status.json`.

The executor checks the document ID and name in Python and again inside InDesign before calling the payload. It temporarily suppresses interaction dialogs and restores the prior interaction setting. It does not change ruler units or save, close, export, convert or create documents implicitly.

The payload is trusted code, not sandboxed. It can access the InDesign application; document guards do not authorize unrelated operations. Layout payloads belong in `latin-book-typography/scripts/` or the applicable skill, not in this bridge.

## Recovery and limits

- Jobs sharing a target process use an advisory Windows mutex. Other executors that do not use this mutex are not coordinated by it.
- An existing job directory is never replayed, regardless of its state. Inspect records and the actual document before deciding whether a new job is appropriate.
- `FAILED` does not imply rollback: a payload may make partial changes before returning an error.
- `UNKNOWN`, an interrupted COM call, or a leftover `RUNNING` state requires inspection before any retry. The executor does not retry mutations automatically or provide a cancellable timeout for synchronous `DoScript`.
- The read-only before/after comparison is metadata evidence, not an exhaustive content or geometry comparison.
- This route does not establish unattended cloud-document saving or safe cloud/local conversion. Preserve document identity and approved save scope explicitly.
- Keep InDesign and the Python process at compatible user/elevation levels. Recheck registration and behavior after Adobe updates; do not reinstall Adobe or modify its registrations automatically.
- A script is complete only after its actual result and document state are inspected. Native Undo is not a qualified recovery mechanism here.

## Tests and validation scope

The original discovery, running-version attachment and read-only `DoScript` approach was exercised in the originating Windows workflow. This reusable package adds instance ambiguity checks, dynamic enum lookup, document guards and persistent execution states.

The unit suite uses fake COM objects and does not launch or edit InDesign:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

If Node is available, three additional wrapper tests evaluate the generated JavaScript with a fake application to check identity guards, JSON serialization and preference restoration. They are skipped when Node is unavailable; this remains an emulation, not a native InDesign test.

Package verification on 2026-11-19 identified the installed Windows registrations and confirmed that no InDesign process was running. The live probe correctly refused activation. No book was opened or modified; a successful live application probe for this packaged revision remains to be run with InDesign open.

Run `discover` and `probe` on each actual installation. Unit tests do not replace a live application probe. A guarded mutation must also be verified on an authorized disposable document before being treated as qualified for a particular operation.
