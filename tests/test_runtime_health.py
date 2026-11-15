import json
import os
import tempfile
import unittest
from unittest.mock import patch

from module.base import runtime_health
from module.device.screenshot import Screenshot
from alas import AzurLaneAutoScript
from module.exception import GamePageUnknownError


class FakeClock:
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


class RuntimeHealthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()

    def tearDown(self):
        self.temp.cleanup()

    def document(self):
        with open(os.path.join(self.temp.name, 'alas2.json'), encoding='utf-8') as stream:
            return json.load(stream)

    def test_start_writes_schema_and_initial_active_state(self):
        with patch.object(runtime_health.time, 'time', self.clock), \
                patch.object(runtime_health, 'HEALTH_DIR', self.temp.name), \
                patch.object(runtime_health, '_tracker', None):
            runtime_health.start('alas2')
        data = self.document()
        self.assertEqual(data, {
            'schema_version': 1,
            'profile': 'alas2',
            'pid': os.getpid(),
            'started_at': 1000,
            'phase': 'waiting',
            'task': '',
            'updated_at': 1000,
        })

    def test_active_and_waiting_transitions_are_flushed(self):
        tracker = runtime_health.RuntimeHealth('alas2', self.temp.name, self.clock)
        with patch.object(runtime_health, '_tracker', tracker):
            self.clock.value += 4
            runtime_health.begin_task('OpsiExplore')
            self.assertEqual(self.document()['phase'], 'active')
            self.assertEqual(self.document()['task'], 'OpsiExplore')
            self.assertEqual(self.document()['updated_at'], 1004)
            self.clock.value += 3
            runtime_health.waiting()
            self.assertEqual(self.document()['phase'], 'waiting')
            self.assertEqual(self.document()['updated_at'], 1007)

    def test_waiting_can_publish_selected_task_without_marking_it_active(self):
        tracker = runtime_health.RuntimeHealth('alas2', self.temp.name, self.clock)
        with patch.object(runtime_health, '_tracker', tracker):
            self.clock.value += 4
            runtime_health.waiting('OpsiExplore')
        self.assertEqual(self.document()['phase'], 'waiting')
        self.assertEqual(self.document()['task'], 'OpsiExplore')
        self.assertEqual(self.document()['updated_at'], 1004)

    def test_pulse_is_throttled_and_state_changes_force_write(self):
        tracker = runtime_health.RuntimeHealth('alas2', self.temp.name, self.clock)
        with patch.object(runtime_health, '_tracker', tracker):
            self.clock.value += 29
            runtime_health.pulse()
            self.assertEqual(self.document()['updated_at'], 1000)
            self.clock.value += 1
            runtime_health.pulse()
            self.assertEqual(self.document()['updated_at'], 1030)
            self.clock.value += 1
            runtime_health.begin_task('Restart')
            self.assertEqual(self.document()['updated_at'], 1031)

    def test_unset_tracker_calls_are_noops(self):
        with patch.object(runtime_health, '_tracker', None):
            runtime_health.begin_task('Restart')
            runtime_health.waiting()
            runtime_health.pulse()

    def test_io_failure_does_not_escape_or_spam_warning(self):
        bad_dir = os.path.join(self.temp.name, 'file')
        with open(bad_dir, 'w', encoding='utf-8') as stream:
            stream.write('not a directory')
        with patch.object(runtime_health.logger, 'warning') as warning:
            tracker = runtime_health.RuntimeHealth('alas2', bad_dir, self.clock)
            tracker.begin_task('Restart')
            tracker.waiting()
        warning.assert_called_once()

    def test_profile_filename_is_restricted(self):
        for profile in ('../alas', 'alas/other', '', 'alas.json', 'x y'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                runtime_health.RuntimeHealth(profile, self.temp.name, self.clock)
        runtime_health.RuntimeHealth('alas-2_test', self.temp.name, self.clock)

    def test_screenshot_pulses_at_entry_and_after_capture_only(self):
        screenshot = object.__new__(Screenshot)

        class Interval:
            def wait(self):
                pass

            def reset(self):
                pass

        class Config:
            Emulator_ScreenshotMethod = 'fake'
            Emulator_ScreenshotDedithering = False
            Error_SaveError = False

        screenshot._screenshot_interval = Interval()
        screenshot.config = Config()
        screenshot.screenshot_methods = {'fake': lambda: events.append('capture') or object()}
        screenshot._handle_orientated_image = lambda image: image
        screenshot.check_screen_size = lambda: True
        screenshot.check_screen_black = lambda: True
        events = []
        with patch.object(runtime_health, 'pulse', side_effect=lambda: events.append('pulse')):
            screenshot.screenshot()
            self.assertEqual(events, ['pulse', 'capture', 'pulse'])
            events.clear()
            screenshot.screenshot_methods = {'fake': lambda: (_ for _ in ()).throw(RuntimeError('capture failed'))}
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                screenshot.screenshot()
        self.assertEqual(events, ['pulse'])

    def test_run_marks_waiting_before_maintenance_block(self):
        script = object.__new__(AzurLaneAutoScript)
        events = []
        checker = type('Checker', (), {
            'check_now': lambda self: None,
            'is_available': lambda self: False,
            'wait_until_available': lambda self: events.append('checker-wait'),
        })()
        script.checker = checker
        script.device = type('Device', (), {'screenshot': lambda self: None})()
        script.maintenance_probe = lambda: (_ for _ in ()).throw(GamePageUnknownError())
        with patch.object(runtime_health, 'waiting', side_effect=lambda: events.append('health-wait')):
            self.assertFalse(script._run('maintenance_probe'))
        self.assertEqual(events, ['health-wait', 'checker-wait'])

    def test_get_next_task_publishes_future_task_before_all_idle_optimizations(self):
        class StopAtWait(Exception):
            pass

        for method in ('close_game', 'goto_main', 'stay_there', 'invalid'):
            with self.subTest(method=method):
                tracker = runtime_health.RuntimeHealth('alas2', self.temp.name, self.clock)
                script = object.__new__(AzurLaneAutoScript)
                task = type('Task', (), {
                    'command': 'OpsiExplore',
                    'next_run': __import__('datetime').datetime.now() + __import__('datetime').timedelta(hours=1),
                })()
                config = type('Config', (), {
                    'get_next': lambda self: task,
                    'bind': lambda self, selected: None,
                    'Optimization_WhenTaskQueueEmpty': method,
                    'task_call': lambda self, name: None,
                })()
                script.config = config
                device_events = []
                script.device = type('Device', (), {
                    'app_stop': lambda self: device_events.append('app_stop'),
                    'release_during_wait': lambda self: device_events.append('release'),
                })()
                script.run = lambda name: device_events.append(name)
                events = []

                def stop_at_wait(future):
                    data = self.document()
                    events.append((data['phase'], data['task']))
                    raise StopAtWait()

                script.wait_until = stop_at_wait
                script.is_first_task = True
                config.task = None
                with patch.object(runtime_health, '_tracker', tracker), \
                        patch('module.base.resource.release_resources'), \
                        patch('alas.AzurLaneConfig.is_hoarding_task', False, create=True), \
                        patch('alas.logger.info'), patch('alas.logger.warning'):
                    with self.assertRaises(StopAtWait):
                        script.get_next_task()
                self.assertEqual(events, [('waiting', 'OpsiExplore')])
                self.assertEqual(self.document()['phase'], 'waiting')


if __name__ == '__main__':
    unittest.main()
