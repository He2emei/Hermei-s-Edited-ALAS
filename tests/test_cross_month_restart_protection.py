"""Exercise the real scheduler exception path from the Nov 1 overnight failures."""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
from module.exception import (
    GameBugError,
    GameNotRunningError,
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
)


OLD_RUN = datetime(2026, 10, 31, 23, 50)
AFTER_RESET = datetime(2026, 11, 1, 0, 42, 59)


class CrossMonthRestartProtectionTests(unittest.TestCase):
    def make_app(self, profile='alas', command='opsi_cross_month', error=None,
                 next_run=OLD_RUN, skip=False):
        app = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        app.config_name = profile
        app.config = SimpleNamespace(
            task=SimpleNamespace(next_run=next_run),
            OpsiCrossMonth_SkipPendingCatchUp=skip,
            task_call=Mock(),
        )
        app.device = Mock(package='com.bilibili.azurlane')
        setattr(app, command, Mock(side_effect=error))
        app.save_error_log = Mock()
        app._notify_error = Mock()
        return app

    def call_at_reset(self, app, command='opsi_cross_month'):
        with patch('alas.datetime', wraps=datetime) as clock:
            clock.now.return_value = AFTER_RESET
            return app.run(command)

    def test_old_world_restart_failures_request_takeover_for_both_profiles(self):
        error_types = (GameNotRunningError, GameStuckError, GameTooManyClickError, GameBugError)
        for profile in ('alas', 'alas2'):
            for error_type in error_types:
                with self.subTest(profile=profile, error=error_type.__name__):
                    app = self.make_app(profile, error=error_type('simulated failure'))
                    with self.assertRaisesRegex(
                        RequestHumanTakeover, 'Overdue OpsiCrossMonth cannot confirm'
                    ):
                        self.call_at_reset(app)
                    app.config.task_call.assert_not_called()
                    app.device.sleep.assert_not_called()
                    self.assertEqual(app.config.task.next_run, OLD_RUN)
                    self.assertFalse(app.config.OpsiCrossMonth_SkipPendingCatchUp)
                    app._notify_error.assert_called_once()
                    if error_type in (GameStuckError, GameTooManyClickError, GameBugError):
                        app.save_error_log.assert_called_once()

    def test_other_task_keeps_ordinary_restart_behavior(self):
        app = self.make_app(command='ordinary_task', error=GameTooManyClickError('click'))
        self.assertFalse(self.call_at_reset(app, 'ordinary_task'))
        app.config.task_call.assert_called_once_with('Restart')
        app.device.sleep.assert_called_once_with(10)
        app._notify_error.assert_not_called()

    def test_cross_month_restart_is_allowed_outside_pending_old_world(self):
        cases = (
            ('before_clearout_window', datetime(2026, 10, 28, 23, 50), AFTER_RESET, False),
            ('future_rescheduled', datetime(2026, 11, 2, 0, 0), AFTER_RESET, False),
            ('explicit_skip', OLD_RUN, AFTER_RESET, True),
            ('before_reset', OLD_RUN, datetime(2026, 10, 31, 23, 59), False),
        )
        for label, next_run, now, skip in cases:
            with self.subTest(case=label):
                app = self.make_app(error=GameTooManyClickError('click'), next_run=next_run, skip=skip)
                with patch('alas.datetime', wraps=datetime) as clock:
                    clock.now.return_value = now
                    self.assertFalse(app.run('opsi_cross_month'))
                app.config.task_call.assert_called_once_with('Restart')
                app.device.sleep.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
