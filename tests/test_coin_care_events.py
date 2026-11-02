import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.reward.coin_resource import CoinResourceStatus
from module.reward.reward import Reward
from module.statistics.coin_care_events import emit_coin_care_event


class CoinCareEventTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 11, 2, 3, tzinfo=timezone.utc)
        self.readings = [(10000, 10000), (10000, 10000), (10000, 10000)]
        self.status = CoinResourceStatus(10000, 10000)
        self.launcher = Mock()
        self.launcher.return_value = SimpleNamespace(returncode=0)

    def tearDown(self):
        self.temp.cleanup()

    def emit(self, profile='alas', **kwargs):
        return emit_coin_care_event(
            profile,
            self.status,
            self.readings,
            root=self.root,
            now=self.now,
            launcher=self.launcher,
            **kwargs,
        )

    def test_requires_two_identical_valid_full_store_readings(self):
        path = self.emit()

        self.assertIsNotNone(path)
        payload = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(payload['kind'], 'coin_overflow')
        self.assertEqual(payload['profile'], 'alas')
        self.assertEqual(payload['coins_current'], 10000)
        self.assertEqual(payload['coins_limit'], 10000)
        self.assertEqual(payload['worker_pid'], __import__('os').getpid())
        self.launcher.assert_called_once()
        args, kwargs = self.launcher.call_args
        self.assertEqual(args[0], ['schtasks.exe', '/Run', '/TN', 'ALAS-Resource-Care'])
        self.assertEqual(kwargs['timeout'], 3)

    def test_rejects_median_without_two_matching_frames(self):
        self.readings = [(10000, 10000), (12000, 10000), (14000, 10000)]
        self.status = CoinResourceStatus(12000, 10000)

        self.assertIsNone(self.emit())
        self.launcher.assert_not_called()

    def test_two_matching_frames_outvote_one_other_valid_reading(self):
        self.readings = [(10000, 10000), (12000, 10000), (10000, 10000)]
        path = self.emit()
        self.assertIsNotNone(path)
        event = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(event['readings'], [[10000, 10000], [10000, 10000]])
        self.launcher.assert_called_once()

    def test_rejects_current_below_limit_and_unknown_or_negative_values(self):
        self.readings = [(9999, 10000), (9999, 10000)]
        self.status = CoinResourceStatus(9999, 10000)
        self.assertIsNone(self.emit())

        self.readings = [(-1, 10000), (-1, 10000)]
        self.status = CoinResourceStatus(-1, 10000)
        self.assertIsNone(self.emit())
        self.launcher.assert_not_called()

    def test_rejects_unapproved_profile_and_limit_below_minimum(self):
        self.assertIsNone(self.emit('template'))
        self.readings = [(9000, 9999), (9000, 9999)]
        self.status = CoinResourceStatus(9000, 9999)
        self.assertIsNone(self.emit())
        self.launcher.assert_not_called()

    def test_rejects_status_that_disagrees_with_raw_consensus(self):
        self.status = CoinResourceStatus(11000, 10000)

        self.assertIsNone(self.emit())

    def test_same_profile_window_is_idempotent_and_does_not_overwrite(self):
        path = self.emit()
        original = path.read_bytes()
        self.now += timedelta(hours=2)

        self.assertIsNone(self.emit())
        self.assertEqual(path.read_bytes(), original)
        self.launcher.assert_called_once()

    def test_profiles_and_later_windows_are_independent(self):
        first = self.emit('alas')
        second = self.emit('alas2')
        self.now += timedelta(hours=13)
        third = self.emit('alas')

        self.assertNotEqual(first.name, second.name)
        self.assertNotEqual(first.name, third.name)
        self.assertEqual(len(list((self.root / 'events').glob('*.json'))), 3)
        self.assertEqual(self.launcher.call_count, 3)

    def test_launch_failure_keeps_event(self):
        self.launcher.side_effect = OSError('offline')

        path = self.emit()

        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['profile'], 'alas')

    def test_nonzero_launcher_result_keeps_event(self):
        self.launcher.return_value = SimpleNamespace(returncode=1, stderr=b'secret')

        path = self.emit()

        self.assertTrue(path.exists())
        self.assertNotIn('secret', path.read_text(encoding='utf-8'))

    def test_write_failure_is_warning_only(self):
        with patch('module.statistics.coin_care_events.Path.open', side_effect=OSError('disk')):
            result = self.emit()

        self.assertIsNone(result)
        self.launcher.assert_not_called()

    def test_fsync_failure_retains_visible_artifact_without_launch_or_retry(self):
        with patch('module.statistics.coin_care_events.os.fsync', side_effect=OSError('disk')):
            result = self.emit()
        self.assertIsNone(result)
        artifacts = list((self.root / 'events').glob('*.json'))
        self.assertEqual(len(artifacts), 1)
        self.assertIsNone(self.emit())
        self.launcher.assert_not_called()

    def test_non_windows_records_without_launching_task(self):
        with patch('module.statistics.coin_care_events.sys.platform', 'linux'):
            path = self.emit()

        self.assertTrue(path.exists())
        self.launcher.assert_not_called()


class CoinCareRewardSeamTest(unittest.TestCase):
    def make_reward(self, enabled=True, last=None):
        reward = object.__new__(Reward)
        reward.config = SimpleNamespace(
            config_name='alas2',
            CoinOverflowWarning_Enable=enabled,
            CoinOverflowWarning_StorageThreshold=0.98,
            CoinOverflowWarning_CooldownHours=12,
            CoinOverflowWarning_LastNotification=last,
        )
        reward._coin_care_readings = [(10000, 10000), (10000, 10000)]
        return reward

    def test_resource_status_preserves_raw_coin_readings(self):
        reward = object.__new__(Reward)
        reward.device = SimpleNamespace(image=object(), screenshot=Mock())
        reward.config = SimpleNamespace(config_name='alas')
        reward.ui_ensure = Mock()
        reward.ui_goto = Mock()
        readings = [(10000, 10000), (10000, 10000), (10000, 10000)]

        with patch('module.reward.reward.read_coin_storage', side_effect=readings), \
                patch('module.config.server.server', 'en', create=True):
            reward._coin_resource_status()

        self.assertEqual(reward._coin_care_readings, readings)

    def test_event_emits_before_qq_cooldown_and_only_when_warning_enabled(self):
        now = datetime(2026, 11, 2, 3)
        status = CoinResourceStatus(10000, 10000)
        reward = self.make_reward(last=now - timedelta(hours=1))
        reward.config.CoinOverflowWarning_LastNotification = now - timedelta(hours=1)
        reading = reward._coin_care_readings
        with tempfile.TemporaryDirectory() as temp:
            launcher = Mock()
            launcher.return_value = SimpleNamespace(returncode=0)

            def emit(profile, observed_status, readings):
                return emit_coin_care_event(
                    profile, observed_status, readings, root=Path(temp),
                    now=now.replace(tzinfo=timezone.utc), launcher=launcher)

            with patch('module.reward.reward.emit_coin_care_event', side_effect=emit), \
                    patch('module.reward.reward.send_notification') as send:
                result = reward._coin_overflow_warning(status, now=now)

            send.assert_not_called()
            self.assertFalse(result)
            event_files = list((Path(temp) / 'events').glob('*.json'))
            self.assertEqual(len(event_files), 1)
            payload = json.loads(event_files[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['readings'], [list(pair) for pair in reading])
            launcher.assert_called_once()

        disabled = self.make_reward(enabled=False)
        with patch('module.reward.reward.emit_coin_care_event') as emit:
            disabled._coin_overflow_warning(status, now=now)
        emit.assert_not_called()

    def test_warning_below_hard_full_threshold_does_not_emit_event(self):
        reward = self.make_reward()
        status = CoinResourceStatus(9800, 10000)

        with tempfile.TemporaryDirectory() as temp, \
                patch('module.reward.reward.emit_coin_care_event',
                      side_effect=lambda profile, observed, readings: emit_coin_care_event(
                          profile, observed, readings, root=Path(temp),
                          launcher=self_launcher, now=datetime(2026, 11, 2))):
            self_launcher = Mock()
            self_launcher.return_value = SimpleNamespace(returncode=0)
            with patch('module.reward.reward.send_notification', return_value=False):
                reward._coin_overflow_warning(status, now=datetime(2026, 11, 2))

            self.assertEqual(list((Path(temp) / 'events').glob('*.json')), [])
            self_launcher.assert_not_called()


if __name__ == '__main__':
    unittest.main()
