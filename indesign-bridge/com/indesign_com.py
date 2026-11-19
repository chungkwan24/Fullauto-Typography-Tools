#!/usr/bin/env python3
"""Discover and probe an already-running Windows InDesign COM server.

No document creation, editing, saving or closing occurs in this module's CLI.
Use connection() from an explicitly authorized executor for document work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys


class BridgeError(RuntimeError):
    """The intended existing application could not be identified or verified."""


def executable_from_server(command: str) -> str:
    """Read quoted or unquoted LocalServer32 executable paths with arguments."""
    command = ntpath.expandvars(command.strip())
    pattern = r'^"([^"]+\.exe)"(?:\s|$)' if command.startswith('"') else r'^(.+?\.exe)(?:\s|$)'
    match = re.match(pattern, command, re.IGNORECASE)
    if not match:
        raise BridgeError("Cannot parse the registered LocalServer32 executable")
    return ntpath.normcase(ntpath.normpath(match.group(1)))


def normal_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


@dataclass(frozen=True)
class Target:
    pid: int
    executable: str
    progid: str


def select_target(registrations: list[dict], processes: list[dict], pid: int | None = None) -> Target:
    candidates = [p for p in processes if pid is None or int(p["pid"]) == pid]
    if not candidates:
        raise BridgeError("No matching InDesign process is visible in this execution context; check sandbox, desktop session and process permissions before concluding InDesign is closed")
    if len(candidates) != 1:
        raise BridgeError("Need one identifiable running InDesign process; use --pid for distinct installed versions")
    process = candidates[0]
    executable = normal_path(process["executable"])
    # A ProgID cannot select between two processes of the same installed version.
    if sum(normal_path(p["executable"]) == executable for p in processes) != 1:
        raise BridgeError("Multiple processes use the same InDesign executable; COM instance selection is ambiguous")
    matches = set()
    for registration in registrations:
        if registration["progid"].lower() == "indesign.application":
            continue
        try:
            if executable_from_server(registration["server"]) == executable:
                matches.add((registration["progid"], registration["clsid"].lower()))
        except BridgeError:
            continue
    if len(matches) != 1:
        raise BridgeError("No unique version-specific COM registration matches the running executable")
    progid, _ = matches.pop()
    return Target(int(process["pid"]), executable, progid)


class WindowsRuntime:
    def __init__(self):
        if os.name != "nt":
            raise BridgeError("Windows COM requires Windows")
        try:
            import pythoncom
            import win32api
            import win32com.client.dynamic
            import win32event
            import winreg
        except ImportError as error:
            raise BridgeError("Install this directory's requirements with the Python interpreter you will use") from error
        self.com = pythoncom
        self.dynamic = win32com.client.dynamic
        self.events = win32event
        self.api = win32api
        self.registry = winreg

    def processes(self) -> list[dict]:
        script = (
            '[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); '
            '@(Get-Process -Name InDesign -ErrorAction SilentlyContinue | '
            'Select-Object Id,Path) | ConvertTo-Json -Compress'
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, encoding="utf-8-sig", check=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        entries = json.loads(result.stdout.strip() or "[]")
        if isinstance(entries, dict):
            entries = [entries]
        if any(not entry.get("Path") for entry in entries):
            raise BridgeError("A running InDesign executable path is inaccessible; check process permissions")
        return [{"pid": int(entry["Id"]), "executable": entry["Path"]} for entry in entries]

    def registrations(self) -> list[dict]:
        reg = self.registry
        found = {}
        for view in (reg.KEY_WOW64_64KEY, reg.KEY_WOW64_32KEY):
            try:
                with reg.OpenKey(reg.HKEY_CLASSES_ROOT, "", 0, reg.KEY_READ | view) as root:
                    for index in range(reg.QueryInfoKey(root)[0]):
                        name = reg.EnumKey(root, index)
                        if not (name == "InDesign.Application" or name.startswith("InDesign.Application.")):
                            continue
                        try:
                            with reg.OpenKey(root, name + r"\CLSID", 0, reg.KEY_READ | view) as key:
                                clsid = reg.QueryValue(key, "")
                            with reg.OpenKey(root, "CLSID\\" + clsid + r"\LocalServer32", 0, reg.KEY_READ | view) as key:
                                server = reg.QueryValue(key, "")
                            found[(name, clsid, server)] = {"progid": name, "clsid": clsid, "server": server}
                        except OSError:
                            continue
            except OSError:
                continue
        return list(found.values())

    def initialize(self):
        self.com.CoInitialize()

    def uninitialize(self):
        self.com.CoUninitialize()

    def lock(self, pid: int):
        handle = self.events.CreateMutex(None, False, "Local\\FullautoTypographyInDesignCOM-" + str(pid))
        result = self.events.WaitForSingleObject(handle, 0)
        if result != 0:
            if result == 128:  # WAIT_ABANDONED grants ownership; release before stopping.
                self.events.ReleaseMutex(handle)
            self.api.CloseHandle(handle)
            raise BridgeError("Another bridge job is active or abandoned; inspect its state before retrying")
        return handle

    def unlock(self, handle):
        self.events.ReleaseMutex(handle)
        self.api.CloseHandle(handle)

    def attach(self, progid: str):
        try:
            obj = self.com.GetActiveObject(progid)
            method = "GetActiveObject"
        except self.com.com_error:
            # Only reached after uniquely matching an already-running executable.
            obj = self.com.CoCreateInstance(
                progid, None, self.com.CLSCTX_LOCAL_SERVER, self.com.IID_IDispatch
            )
            method = "CoCreateInstance for verified running version"
        return self.dynamic.Dispatch(obj), method


@dataclass
class Connection:
    app: object
    target: Target
    activation: str

    def metadata(self) -> dict:
        return {**asdict(self.target), "activation": self.activation}


@contextmanager
def connection(pid: int | None = None, runtime=None):
    """Attach to one identified running version; never deliberately launch InDesign."""
    runtime = runtime or WindowsRuntime()
    target = select_target(runtime.registrations(), runtime.processes(), pid)
    runtime.initialize()
    handle = None
    try:
        handle = runtime.lock(target.pid)
        app, activation = runtime.attach(target.progid)
        # Some COM activations may start a server. Do not silently accept a new PID.
        after = select_target(runtime.registrations(), runtime.processes(), target.pid)
        if after != target:
            raise BridgeError("The running application changed during COM activation")
        yield Connection(app, target, activation)
    finally:
        try:
            if handle is not None:
                runtime.unlock(handle)
        finally:
            runtime.uninitialize()


def javascript_language(app) -> int:
    """Resolve JavaScript from this application's installed type library."""
    typelib, _ = app._oleobj_.GetTypeInfo().GetContainingTypeLib()
    values = set()
    for index in range(typelib.GetTypeInfoCount()):
        info = typelib.GetTypeInfo(index)
        if "scriptlanguage" not in info.GetDocumentation(-1)[0].lower():
            continue
        for variable in range(info.GetTypeAttr().cVars):
            description = info.GetVarDesc(variable)
            if "javascript" in info.GetDocumentation(description.memid)[0].lower():
                values.add(int(description.value))
    if len(values) != 1:
        raise BridgeError("No unique JavaScript ScriptLanguage value found in the installed type library")
    return values.pop()


def snapshot(app) -> dict:
    documents = app.Documents
    result = []
    for index in range(1, int(documents.Count) + 1):
        document = documents.Item(index)
        result.append({"id": int(document.ID), "name": str(document.Name),
                       "pages": int(document.Pages.Count), "modified": bool(document.Modified)})
    return {"version": str(app.Version), "documents": result}


def probe(session: Connection) -> dict:
    before = snapshot(session.app)
    language = javascript_language(session.app)
    result = str(session.app.DoScript(
        '"COM_READ_ONLY_OK|" + app.version + "|" + app.documents.length;', language
    ))
    after = snapshot(session.app)
    expected = "COM_READ_ONLY_OK|" + before["version"] + "|" + str(len(before["documents"]))
    if result != expected or before != after:
        raise BridgeError("Read-only probe or before/after document metadata verification failed")
    return {"status": "passed", "read_only": True, "connection": session.metadata(),
            "javascript_language": language, "doscript_result": result,
            "before": before, "after": after, "metadata_unchanged": True}


def write_report(report: dict, output: Path | None = None):
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "probe"))
    parser.add_argument("--pid", type=int, help="Select one of distinct running installed versions")
    parser.add_argument("--output", type=Path, help="Optional new JSON report file; never overwrites")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and args.output.exists():
            raise BridgeError("Output already exists; choose a new report path")
        if args.command == "discover":
            runtime = WindowsRuntime()
            processes = runtime.processes()
            report = {"registrations": runtime.registrations(), "processes": processes, "read_only": True,
                      "process_visibility": "processes_observed" if processes else "no_processes_visible"}
            if not processes:
                report["warning"] = ("An empty process list does not prove InDesign is closed. "
                                     "A sandbox, desktop session or permission boundary can hide it. "
                                     "Verify authorized desktop access before launching another instance.")
        else:
            with connection(args.pid) as session:
                report = probe(session)
        write_report(report, args.output)
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
