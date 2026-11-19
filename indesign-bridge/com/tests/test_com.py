import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import indesign_com as bridge
import run_jsx


EXE = r"C:\Adobe Suite\InDesign\InDesign.exe"
REG = {"progid": "InDesign.Application.Test", "clsid": "{test}", "server": '"' + EXE + '" /Automation'}
PROCESS = {"pid": 123, "executable": EXE}


class FakeDocuments:
    def __init__(self):
        self.items = [NS(ID=7, Name="Test.indd", Pages=NS(Count=4), Modified=False)]

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index - 1]


class FakeApp:
    Version = "test-version"

    def __init__(self):
        self.Documents = FakeDocuments()
        self.calls = []
        self.outcome = '{"state":"COMPLETE","result":{"checked":true}}'

    def DoScript(self, source, language):
        self.calls.append((source, language))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeRuntime:
    def __init__(self):
        self.app = FakeApp()
        self.process_list = [PROCESS]
        self.after = None
        self.attaches = 0
        self.initialized = 0
        self.uninitialized = 0
        self.unlocked = 0

    def registrations(self):
        return [REG]

    def processes(self):
        return self.after if self.attaches and self.after is not None else self.process_list

    def initialize(self):
        self.initialized += 1

    def uninitialize(self):
        self.uninitialized += 1

    def lock(self, pid):
        return pid

    def unlock(self, handle):
        self.unlocked += 1

    def attach(self, progid):
        self.attaches += 1
        return self.app, "fake-existing-server"


class SelectionTests(unittest.TestCase):
    def test_quoted_registration_with_arguments(self):
        self.assertEqual(bridge.select_target([REG], [PROCESS]).progid, REG["progid"])

    def test_unquoted_registration_and_case(self):
        registration = {**REG, "server": EXE.upper() + " /Automation"}
        self.assertEqual(bridge.select_target([registration], [PROCESS]).pid, 123)

    def test_generic_registration_is_not_a_target(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.select_target([{**REG, "progid": "InDesign.Application"}], [PROCESS])

    def test_no_process_prevents_activation(self):
        runtime = FakeRuntime()
        runtime.process_list = []
        with self.assertRaises(bridge.BridgeError), bridge.connection(runtime=runtime):
            pass
        self.assertEqual(runtime.attaches, 0)

    def test_pid_does_not_resolve_same_executable_instances(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.select_target([REG], [PROCESS, {**PROCESS, "pid": 456}], pid=123)

    def test_explicit_pid_selects_distinct_version(self):
        other = {"pid": 456, "executable": r"C:\Other\InDesign.exe"}
        self.assertEqual(bridge.select_target([REG], [PROCESS, other], pid=123).pid, 123)

    def test_multiple_specific_registrations_are_ambiguous(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.select_target([REG, {**REG, "progid": "InDesign.Application.Other"}], [PROCESS])

    def test_duplicate_registry_views_are_deduplicated(self):
        self.assertEqual(bridge.select_target([REG, REG], [PROCESS]).pid, 123)

    def test_new_process_after_activation_is_rejected_and_released(self):
        runtime = FakeRuntime()
        runtime.after = [PROCESS, {**PROCESS, "pid": 456}]
        with self.assertRaises(bridge.BridgeError), bridge.connection(runtime=runtime):
            pass
        self.assertEqual(runtime.unlocked, 1)
        self.assertEqual(runtime.uninitialized, 1)


class ProbeTests(unittest.TestCase):
    def test_empty_discovery_reports_visibility_limit_without_activation(self):
        runtime = FakeRuntime()
        runtime.process_list = []
        with patch.object(bridge, "WindowsRuntime", return_value=runtime), patch.object(bridge, "write_report") as writer:
            self.assertEqual(bridge.main(["discover"]), 0)
        report = writer.call_args.args[0]
        self.assertEqual(report["processes"], [])
        self.assertEqual(report["process_visibility"], "no_processes_visible")
        self.assertTrue(report.get("warning"))
        self.assertEqual(runtime.attaches, 0)

    def test_visible_discovery_does_not_activate_com(self):
        runtime = FakeRuntime()
        with patch.object(bridge, "WindowsRuntime", return_value=runtime), patch.object(bridge, "write_report") as writer:
            self.assertEqual(bridge.main(["discover"]), 0)
        report = writer.call_args.args[0]
        self.assertEqual(report["process_visibility"], "processes_observed")
        self.assertNotIn("warning", report)
        self.assertEqual(runtime.attaches, 0)

    def test_probe_preserves_metadata_and_uses_resolved_language(self):
        runtime = FakeRuntime()
        runtime.app.outcome = "COM_READ_ONLY_OK|test-version|1"
        with patch.object(bridge, "javascript_language", return_value=2468):
            with bridge.connection(runtime=runtime) as session:
                report = bridge.probe(session)
        self.assertTrue(report["metadata_unchanged"])
        self.assertEqual(runtime.app.calls[0][1], 2468)
        self.assertEqual(runtime.uninitialized, 1)

    def test_probe_rejects_changed_document_metadata(self):
        runtime = FakeRuntime()
        before = bridge.snapshot(runtime.app)
        after = {**before, "documents": []}
        runtime.app.outcome = "COM_READ_ONLY_OK|test-version|1"
        with patch.object(bridge, "javascript_language", return_value=2468), patch.object(bridge, "snapshot", side_effect=[before, after]):
            with bridge.connection(runtime=runtime) as session, self.assertRaises(bridge.BridgeError):
                bridge.probe(session)

    def test_javascript_enum_is_discovered_without_a_fixed_value(self):
        info = NS(GetDocumentation=lambda member: ("ScriptLanguage" if member == -1 else "idJavascript",),
                  GetTypeAttr=lambda: NS(cVars=1), GetVarDesc=lambda index: NS(memid=10, value=9876))
        library = NS(GetTypeInfoCount=lambda: 1, GetTypeInfo=lambda index: info)
        app = NS(_oleobj_=NS(GetTypeInfo=lambda: NS(GetContainingTypeLib=lambda: (library, 0))))
        self.assertEqual(bridge.javascript_language(app), 9876)

    def test_report_does_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                bridge.write_report({}, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing")


class JobTests(unittest.TestCase):
    def run_fixture(self, folder, runtime, *, document_id=7, job_name="job"):
        script = Path(folder) / "source.jsx"
        script.write_text('(function (doc) { return {name: doc.name}; })', encoding="utf-8")
        with patch.object(run_jsx, "connection", side_effect=lambda pid: bridge.connection(pid, runtime)), patch.object(run_jsx, "javascript_language", return_value=2468):
            return run_jsx.run_job(script, Path(folder) / job_name, document_id, "Test.indd")

    def test_wrong_document_is_rejected_before_dispatch(self):
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(bridge.BridgeError):
                self.run_fixture(folder, runtime, document_id=8)
            state = json.loads((Path(folder) / "job/status.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "FAILED")
        self.assertEqual(runtime.app.calls, [])

    def test_success_records_result_without_implicit_save(self):
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_fixture(folder, runtime)
            self.assertEqual(report["state"], "COMPLETE")
            self.assertEqual(report["result"], {"checked": True})
            self.assertTrue((Path(folder) / "job/payload.jsx").exists())
        self.assertEqual(runtime.app.calls[0][1], 2468)
        self.assertFalse(runtime.app.Documents.Item(1).Modified)

    def test_com_exception_after_dispatch_is_unknown_not_retried(self):
        runtime = FakeRuntime()
        runtime.app.outcome = RuntimeError("connection interrupted")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                self.run_fixture(folder, runtime)
            state = json.loads((Path(folder) / "job/status.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "UNKNOWN")
        self.assertEqual(len(runtime.app.calls), 1)

    def test_invalid_return_after_dispatch_is_unknown(self):
        runtime = FakeRuntime()
        runtime.app.outcome = "not JSON"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                self.run_fixture(folder, runtime)
            state = json.loads((Path(folder) / "job/status.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "UNKNOWN")

    def test_javascript_failure_remains_failed(self):
        runtime = FakeRuntime()
        runtime.app.outcome = '{"state":"FAILED","error":"payload error"}'
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_fixture(folder, runtime)
        self.assertEqual(report["state"], "FAILED")

    def test_existing_job_directory_never_replays(self):
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as folder:
            self.run_fixture(folder, runtime)
            with self.assertRaises(FileExistsError):
                self.run_fixture(folder, runtime)
        self.assertEqual(len(runtime.app.calls), 1)

    def test_include_is_not_silently_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "source.jsx"
            script.write_text('#include "another.jsx"', encoding="utf-8")
            with self.assertRaises(bridge.BridgeError):
                run_jsx.run_job(script, Path(folder) / "job", 7, "Test.indd")
            self.assertFalse((Path(folder) / "job").exists())


@unittest.skipUnless(shutil.which("node"), "Node is optional for wrapper-level JavaScript tests")
class WrapperTests(unittest.TestCase):
    HARNESS = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let evaluated = 0;
const app = {documents: [{id: 7, name: input.name}],
    scriptPreferences: {userInteractionLevel: 31, measurementUnit: 9137}};
const context = vm.createContext({app, File: p => p, UserInteractionLevels: {NEVER_INTERACT: 7}});
context.$ = {evalFile: () => { evaluated++; return vm.runInContext(input.payload, context); }};
const outcome = JSON.parse(vm.runInContext(input.wrapper, context));
process.stdout.write(JSON.stringify({outcome, evaluated, preferences: app.scriptPreferences}));
'''

    def evaluate(self, payload, *, document_id=7):
        name = 'Test "é" 文档.indd'
        wrapper = run_jsx.make_wrapper(Path("payload.jsx"), document_id, name, Path("job"))
        result = subprocess.run([shutil.which("node"), "-e", self.HARNESS],
                                input=json.dumps({"wrapper": wrapper, "payload": payload, "name": name}),
                                text=True, capture_output=True, check=True, encoding="utf-8", timeout=10)
        return json.loads(result.stdout)

    def test_wrapper_checks_identity_before_evaluating_payload(self):
        result = self.evaluate('(function () { throw Error("must not run"); })', document_id=8)
        self.assertEqual(result["evaluated"], 0)
        self.assertEqual(result["outcome"]["state"], "FAILED")
        self.assertEqual(result["preferences"]["userInteractionLevel"], 31)

    def test_wrapper_serializes_values_and_restores_preferences(self):
        result = self.evaluate(r'''(function (doc) { return {name: doc.name, text: 'quote "\n\t', array: [1, null, true]}; })''')
        self.assertEqual(result["outcome"]["state"], "COMPLETE")
        self.assertEqual(result["outcome"]["result"]["array"], [1, None, True])
        self.assertEqual(result["outcome"]["result"]["text"], 'quote "\n\t')
        self.assertEqual(result["preferences"], {"userInteractionLevel": 31, "measurementUnit": 9137})

    def test_wrapper_reports_error_and_restores_preferences(self):
        result = self.evaluate('(function () { throw Error("payload failed"); })')
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["outcome"]["state"], "FAILED")
        self.assertIn("payload failed", result["outcome"]["error"])
        self.assertEqual(result["preferences"]["userInteractionLevel"], 31)


if __name__ == "__main__":
    unittest.main()
