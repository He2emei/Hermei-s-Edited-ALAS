import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if 'inflection' not in sys.modules:
    try:
        import inflection  # noqa: F401
    except ModuleNotFoundError:
        sys.modules['inflection'] = types.SimpleNamespace(underscore=lambda value: value)

from alas import AzurLaneAutoScript
from module.exception import GameNotRunningError
from module.notify.napcat import send_error_notification, send_notification


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if '--send' in command:
            return subprocess.CompletedProcess(command, 0, 'Sent to owner.\n', '')
        return subprocess.CompletedProcess(command, 0, 'preview_id: abc123\n', '')


class NapCatErrorNotificationTest(unittest.TestCase):
    def _send_with_project_token(self, project_token, inherited_token=None):
        runner = FakeRunner()
        inherited_environment = {}
        if inherited_token is not None:
            inherited_environment['NAPCAT_ACCESS_TOKEN'] = inherited_token

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text(
                f'NAPCAT_ACCESS_TOKEN={project_token}\n', encoding='utf-8')
            with patch.dict(os.environ, inherited_environment, clear=True), \
                    patch('module.notify.napcat.PROJECT_ENV_FILE', env_file):
                sent = send_error_notification(
                    'alas-test', 'Main', RuntimeError('boom'), runner=runner)
        return runner, sent

    def test_passes_project_dotenv_token_only_through_child_environment(self):
        runner, sent = self._send_with_project_token('test-token-from-dotenv')

        self.assertTrue(sent)
        for command, options in runner.commands:
            self.assertNotIn('test-token-from-dotenv', command)
            self.assertEqual(
                options['env']['NAPCAT_ACCESS_TOKEN'],
                'test-token-from-dotenv',
            )

    def test_project_dotenv_token_overrides_inherited_environment(self):
        runner, sent = self._send_with_project_token(
            'current-project-token', inherited_token='stale-inherited-token')

        self.assertTrue(sent)
        for command, options in runner.commands:
            self.assertNotIn('current-project-token', command)
            self.assertNotIn('stale-inherited-token', command)
            self.assertEqual(
                options['env']['NAPCAT_ACCESS_TOKEN'],
                'current-project-token',
            )

    def test_previews_then_sends_error_to_the_fixed_owner_route(self):
        runner = FakeRunner()

        sent = send_error_notification(
            config_name='alas-test',
            task='OpsiMeowfficerFarming',
            error=RuntimeError('boom'),
            runner=runner,
        )

        self.assertTrue(sent)
        self.assertEqual(len(runner.commands), 2)
        preview, send = [command for command, _ in runner.commands]
        self.assertNotIn('--send', preview)
        self.assertIn('--send', send)
        self.assertEqual(send[send.index('--reason') + 1], 'user-request')
        self.assertEqual(send[send.index('--preview-id') + 1], 'abc123')
        message = preview[preview.index('--message') + 1]
        self.assertIn('alas-test', message)
        self.assertIn('OpsiMeowfficerFarming', message)

    def test_game_not_running_restarts_without_notifying_owner(self):
        class FakeConfig:
            def __init__(self):
                self.calls = []

            def task_call(self, task):
                self.calls.append(task)

        app = object.__new__(AzurLaneAutoScript)
        app.config_name = 'alas-test'
        app.__dict__['config'] = FakeConfig()

        def failing_task():
            raise GameNotRunningError('emulator stopped')

        app.failing_task = failing_task

        with patch('alas.send_error_notification') as notify:
            result = app.run('failing_task', skip_first_screenshot=True)

        self.assertFalse(result)
        self.assertEqual(app.config.calls, ['Restart'])
        notify.assert_not_called()

    def test_failed_automatic_recovery_notifies_before_propagating(self):
        app = object.__new__(AzurLaneAutoScript)
        app.config_name = 'alas-test'
        app.__dict__['config'] = types.SimpleNamespace(
            task_call=lambda task: (_ for _ in ()).throw(
                RuntimeError('cannot schedule restart')),
        )
        app.failing_task = lambda: (_ for _ in ()).throw(
            GameNotRunningError('emulator stopped'))

        with patch('alas.send_error_notification') as notify:
            with self.assertRaisesRegex(RuntimeError, 'cannot schedule restart'):
                app.run('failing_task', skip_first_screenshot=True)

        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][:2], ('alas-test', 'failing_task'))

    def test_third_consecutive_task_failure_notifies_before_exit(self):
        app = object.__new__(AzurLaneAutoScript)
        app.config_name = 'alas-test'
        app.is_first_task = False
        app.failure_record = {'FailingTask': 2}
        app.__dict__['config'] = types.SimpleNamespace(
            Error_OnePushConfig={},
            Error_HandleError=True,
        )
        app.__dict__['checker'] = types.SimpleNamespace(
            wait_until_available=lambda: None,
            is_recovered=lambda: False,
            check_now=lambda: None,
        )
        app.__dict__['device'] = types.SimpleNamespace(
            config=None,
            stuck_record_clear=lambda: None,
            click_record_clear=lambda: None,
        )
        app.get_next_task = lambda: 'FailingTask'
        app.run = lambda command: False

        with patch('alas.send_error_notification') as notify, \
                patch('alas.logger.set_file_logger'), \
                patch('alas.handle_notify'):
            with self.assertRaises(SystemExit):
                app.loop()

        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][:2], ('alas-test', 'FailingTask'))

    def test_does_not_pass_raw_error_details_to_the_helper(self):
        runner = FakeRunner()

        sent = send_error_notification(
            config_name='alas-test',
            task='Main',
            error=RuntimeError('NAPCAT_ACCESS_TOKEN=do-not-expose'),
            runner=runner,
        )

        self.assertTrue(sent)
        preview = runner.commands[0][0]
        message = preview[preview.index('--message') + 1]
        self.assertNotIn('do-not-expose', message)
        self.assertIn('RuntimeError', message)

    def test_sends_each_separate_exception_event(self):
        runner = FakeRunner()

        first = send_error_notification(
            'repeat-config', 'Main', RuntimeError('same text'), runner=runner)
        second = send_error_notification(
            'repeat-config', 'Main', RuntimeError('same text'), runner=runner)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(runner.commands), 4)

    def test_generic_notification_uses_guarded_preview_and_send_flow(self):
        runner = FakeRunner()

        sent = send_notification(
            context='ALAS/resource/alas2/coin',
            message='仓库物资 93000/94200',
            runner=runner,
        )

        self.assertTrue(sent)
        self.assertEqual(len(runner.commands), 2)
        preview, send = [command for command, _ in runner.commands]
        self.assertEqual(
            preview[preview.index('--context') + 1],
            'ALAS/resource/alas2/coin',
        )
        self.assertEqual(
            preview[preview.index('--message') + 1],
            '仓库物资 93000/94200',
        )
        self.assertIn('--send', send)


if __name__ == '__main__':
    unittest.main()
