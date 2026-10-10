import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from module.base.repair_event import emit_terminal_failure


class RepairEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / "AzurLaneAutoScript-Use"
        self.root.mkdir()
        self.tmp = self.workspace / "code_workflow" / "tmp"
        self.tmp.mkdir(parents=True)
        self.launcher = Mock(return_value=SimpleNamespace(returncode=0))
        self.now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def enable(self, provider="Codex"):
        (self.tmp / "alas_repair_settings.json").write_text(
            json.dumps({"enabled": True, "RepairProvider": provider}), encoding="utf-8"
        )

    def emit(self, error=RuntimeError("failure"), **kwargs):
        return emit_terminal_failure("alas", "TaskName", error, root=self.root,
                                     launcher=self.launcher, now=self.now, pid=42, **kwargs)

    def events(self):
        return list((self.root / "log" / "repair_events").glob("*.json"))

    def test_atomic_event_has_only_minimal_fields_and_clamps_line(self):
        result = self.emit(RuntimeError("x" * 700))
        self.assertFalse(result["dispatched"])
        files = self.events()
        self.assertEqual(len(files), 1)
        event = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(set(event), {"schema", "id", "profile", "task", "error_type",
                                      "error_line", "time_utc", "pid"})
        self.assertEqual(event["schema"], 1)
        self.assertEqual(event["pid"], 42)
        self.assertEqual(len(event["error_line"]), 500)
        self.assertEqual(event["profile"], "alas")

    def test_enabled_production_dispatches_once_with_task_name(self):
        self.enable("Hapi")
        result = self.emit()
        self.assertTrue(result["dispatched"])
        self.launcher.assert_called_once()
        args, kwargs = self.launcher.call_args
        self.assertEqual(args[0], ["schtasks.exe", "/Run", "/TN", "ALAS-Repair"])
        self.assertEqual(kwargs["timeout"], 3)
        self.assertTrue(kwargs["capture_output"])

    def test_disabled_by_default_and_invalid_provider(self):
        self.emit()
        self.launcher.assert_not_called()
        self.enable("Disabled")
        self.emit()
        self.launcher.assert_not_called()
        self.assertEqual(len(self.events()), 2)

    def test_month_end_window_includes_start_and_end_boundaries(self):
        self.enable()
        for moment in (datetime(2026, 10, 31, 15, tzinfo=timezone.utc),
                       datetime(2026, 10, 31, 21, 59, tzinfo=timezone.utc)):
            with self.subTest(moment=moment):
                self.launcher.reset_mock()
                emit_terminal_failure("alas", "Task", RuntimeError("x"), root=self.root,
                                      launcher=self.launcher, now=moment)
                self.launcher.assert_not_called()

    def test_dispatch_resumes_after_window(self):
        self.enable()
        moment = datetime(2026, 10, 31, 22, tzinfo=timezone.utc)  # 06:00 China
        result = emit_terminal_failure("alas", "Task", RuntimeError("x"), root=self.root,
                                       launcher=self.launcher, now=moment)
        self.assertTrue(result["dispatched"])

    def test_global_and_profile_pauses_block_dispatch(self):
        self.enable()
        for marker in ("alas_guard.pause", "alas_guard.alas.pause", "alas_guard.repair.pause"):
            with self.subTest(marker=marker):
                (self.tmp / marker).touch()
                self.launcher.reset_mock()
                result = self.emit()
                self.assertEqual(result["reason"], "paused")
                self.launcher.assert_not_called()
                (self.tmp / marker).unlink()

    def test_unknown_profile_is_blocked_by_any_profile_pause(self):
        self.enable()
        (self.tmp / "alas_guard.alas2.pause").touch()
        result = emit_terminal_failure("unknown", "Task", RuntimeError("x"), root=self.root,
                                       launcher=self.launcher, now=self.now)
        self.assertEqual(result["reason"], "paused")
        self.launcher.assert_not_called()

    def test_cross_month_protection_never_dispatches(self):
        self.enable()
        result = self.emit(RuntimeError("Overdue OpsiCrossMonth cannot confirm map"))
        self.assertEqual(result["reason"], "scope_or_protection")
        self.launcher.assert_not_called()
        self.assertEqual(len(self.events()), 1)

    def test_launcher_failure_does_not_escape_or_remove_event(self):
        self.enable()
        self.launcher.side_effect = OSError("task scheduler unavailable")
        result = self.emit()
        self.assertEqual(result["reason"], "event_failure")
        self.assertEqual(len(self.events()), 1)

    def test_nonproduction_checkout_does_not_write_or_dispatch(self):
        self.enable()
        dev_root = self.workspace / "AzurLaneAutoScript-Original"
        dev_root.mkdir()
        result = emit_terminal_failure("alas", "Task", RuntimeError("x"), root=dev_root,
                                       launcher=self.launcher, now=self.now)
        self.assertEqual(result["reason"], "nonproduction")
        self.assertFalse((dev_root / "log").exists())
        self.launcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()

