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
from module.notify.napcat import send_error_notification


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

    def test_scheduler_error_exit_notifies_and_preserves_restart_handling(self):
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
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[:2], ('alas-test', 'failing_task'))

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


if __name__ == '__main__':
    unittest.main()
