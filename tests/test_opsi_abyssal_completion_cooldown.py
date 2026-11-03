import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.os.tasks.abyssal import OpsiAbyssal


class AbyssalCompletionCooldownTest(unittest.TestCase):
    def app(self, result):
        return SimpleNamespace(try_clear_abyssal=Mock(return_value=result),
                               config=SimpleNamespace(task_delay=Mock(), task_stop=Mock()))

    def test_success_on_last_day_keeps_clearing_coordinates(self):
        app = self.app(True)
        with patch('module.os.tasks.abyssal.get_os_reset_remain', return_value=0):
            OpsiAbyssal.clear_abyssal(app)
        app.try_clear_abyssal.assert_called_once_with()
        app.config.task_delay.assert_not_called()
        app.config.task_stop.assert_not_called()

    def test_no_coordinates_on_last_day_delays_150_minutes(self):
        app = self.app(False)
        with patch('module.os.tasks.abyssal.get_os_reset_remain', return_value=0):
            OpsiAbyssal.clear_abyssal(app)
        app.config.task_delay.assert_called_once_with(minute=150, server_update=True)
        app.config.task_stop.assert_called_once_with()

    def test_no_coordinates_on_other_day_waits_for_server_update(self):
        app = self.app(False)
        with patch('module.os.tasks.abyssal.get_os_reset_remain', return_value=3):
            OpsiAbyssal.clear_abyssal(app)
        app.config.task_delay.assert_called_once_with(server_update=True)
        app.config.task_stop.assert_called_once_with()

    def test_unknown_clear_failure_propagates_without_success_delay(self):
        app = self.app(False)
        app.try_clear_abyssal.side_effect = RuntimeError('unknown clear failure')
        with self.assertRaisesRegex(RuntimeError, 'unknown clear failure'):
            OpsiAbyssal.clear_abyssal(app)
        app.config.task_delay.assert_not_called()
        app.config.task_stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()