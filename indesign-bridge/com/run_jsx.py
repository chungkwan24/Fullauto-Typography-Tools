#!/usr/bin/env python3
"""Run one authorized JSX payload against an explicitly identified open document."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from indesign_com import BridgeError, connection, javascript_language, snapshot


SERIALIZER = r'''
function encode(v) {
    function quote(s) { return '"' + String(s).replace(/[\\"\x00-\x1f]/g, function(c) {
        if (c === '"') return '\\"'; if (c === '\\') return '\\\\';
        var h = c.charCodeAt(0).toString(16); return '\\u' + ('0000' + h).slice(-4);
    }) + '"'; }
    if (v === null || typeof v === 'undefined') return 'null';
    if (typeof v === 'string') return quote(v);
    if (typeof v === 'number') return isFinite(v) ? String(v) : 'null';
    if (typeof v === 'boolean') return String(v);
    var a = [], k;
    if (v instanceof Array) { for (k = 0; k < v.length; k++) a.push(encode(v[k])); return '[' + a.join(',') + ']'; }
    for (k in v) if (v.hasOwnProperty(k)) a.push(quote(k) + ':' + encode(v[k]));
    return '{' + a.join(',') + '}';
}
'''


def make_wrapper(payload: Path, document_id: int, document_name: str, job_dir: Path) -> str:
    config = json.dumps({"payload": str(payload), "documentId": document_id,
                         "documentName": document_name, "jobDir": str(job_dir)}, ensure_ascii=True)
    return '(function () {\n' + SERIALIZER + '\nvar cfg = ' + config + r''';
try {
    var doc = null, i;
    for (i = 0; i < app.documents.length; i++) {
        if (app.documents[i].id === cfg.documentId && app.documents[i].name === cfg.documentName) {
            doc = app.documents[i]; break;
        }
    }
    if (!doc) throw Error('Expected open document ID and name do not match');
    var oldInteraction = app.scriptPreferences.userInteractionLevel;
    try {
        app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
        var run = $.evalFile(File(cfg.payload));
        if (typeof run !== 'function') throw Error('Payload must evaluate to function(doc, job, helpers)');
        var result = run(doc, cfg, {encode: encode});
        return encode({state: 'COMPLETE', result: result});
    } finally {
        app.scriptPreferences.userInteractionLevel = oldInteraction;
    }
} catch (e) {
    return encode({state: 'FAILED', error: String(e), line: e.line || null});
}
})();'''


def write_state(directory: Path, report: dict):
    temporary = directory / "status.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "status.json")


def run_job(script: Path, directory: Path, document_id: int, document_name: str, pid=None) -> dict:
    script = script.resolve(strict=True)
    directory = directory.resolve()
    if document_id <= 0 or not document_name:
        raise BridgeError("An explicit document ID and name are required")
    source = script.read_text(encoding="utf-8-sig")
    if re.search(r"^\s*#", source, re.MULTILINE):
        raise BridgeError("Use a self-contained payload without preprocessor directives; includes are not rewritten")
    # Exclusive directory creation prevents replay of PREPARED, RUNNING or failed jobs.
    directory.mkdir(parents=True, exist_ok=False)
    payload = directory / "payload.jsx"
    payload.write_text(source, encoding="utf-8")
    wrapper = make_wrapper(payload, document_id, document_name, directory)
    (directory / "run.jsx").write_text(wrapper, encoding="utf-8")
    report = {"state": "PREPARED", "document_id": document_id, "document_name": document_name,
              "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
    write_state(directory, report)
    invoked = False
    try:
        with connection(pid) as session:
            report["connection"] = session.metadata()
            report["before"] = snapshot(session.app)
            if not any(d["id"] == document_id and d["name"] == document_name for d in report["before"]["documents"]):
                raise BridgeError("Expected open document ID and name do not match")
            language = javascript_language(session.app)
            report["state"] = "RUNNING"
            write_state(directory, report)
            invoked = True
            outcome = json.loads(str(session.app.DoScript(wrapper, language)))
            if not isinstance(outcome, dict) or outcome.get("state") not in ("COMPLETE", "FAILED"):
                raise BridgeError("Unrecognized execution result")
            report.update(outcome)
            report["after"] = snapshot(session.app)
    except BaseException as error:
        # A COM exception after dispatch does not prove that the payload did not run.
        report.update(state="UNKNOWN" if invoked else "FAILED", error=str(error))
        write_state(directory, report)
        raise
    write_state(directory, report)
    return report


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path, help="Trusted self-contained ES3 expression returning a function")
    parser.add_argument("--document-id", required=True, type=int)
    parser.add_argument("--document-name", required=True)
    parser.add_argument("--job-dir", required=True, type=Path, help="New directory; existing directories are never replayed")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args(argv)
    try:
        report = run_job(args.script, args.job_dir, args.document_id, args.document_name, args.pid)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["state"] == "COMPLETE" else 2
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
