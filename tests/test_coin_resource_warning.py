import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from module.reward.coin_resource import CoinResourceStatus
from module.reward.reward import Reward


class CoinResourceStatusTest(unittest.TestCase):
    def test_storage_below_threshold_does_not_warn(self):
        status = CoinResourceStatus(
            storage_current=90000,
            storage_limit=94200,
        )

        warning_reached = status.storage_warning_reached(storage_threshold=0.98)

        self.assertFalse(warning_reached)

    def test_reports_storage_near_capacity(self):
        status = CoinResourceStatus(
            storage_current=93000,
            storage_limit=94200,
        )

        warning_reached = status.storage_warning_reached(storage_threshold=0.98)

        self.assertTrue(warning_reached)
        message = status.notification_message('alas2')
        self.assertIn('93000/94200', message)
        self.assertIn('已达到预警阈值', message)
        self.assertNotIn('小卖部', message)

    def test_unknown_or_invalid_limits_do_not_create_false_warning(self):
        status = CoinResourceStatus(
            storage_current=93000,
            storage_limit=0,
        )

        self.assertEqual(
            status.storage_warning_reached(storage_threshold=0.9),
            False,
        )

    def test_warning_threshold_is_clamped_to_a_safe_range(self):
        status = CoinResourceStatus(
            storage_current=80,
            storage_limit=100,
        )

        self.assertEqual(
            status.storage_warning_reached(storage_threshold=0),
            True,
        )

    def test_cooldown_uses_last_successful_notification(self):
        now = datetime(2026, 8, 27, 16, 0, 0)

        self.assertTrue(CoinResourceStatus.cooldown_elapsed(None, now, 12))
        self.assertFalse(CoinResourceStatus.cooldown_elapsed(
            now - timedelta(hours=11), now, 12))
        self.assertTrue(CoinResourceStatus.cooldown_elapsed(
            now - timedelta(hours=12), now, 12))

    def test_reward_sends_one_combined_warning_and_records_success(self):
        now = datetime(2026, 8, 27, 16, 0, 0)
        reward = object.__new__(Reward)
        reward.config = SimpleNamespace(
            config_name='alas2',
            CoinOverflowWarning_Enable=True,
            CoinOverflowWarning_StorageThreshold=0.95,
            CoinOverflowWarning_CooldownHours=12,
            CoinOverflowWarning_LastNotification=datetime(2020, 1, 1),
        )
        status = CoinResourceStatus(94000, 94200)

        with patch('module.reward.reward.send_notification', return_value=True) as send:
            sent = reward._coin_overflow_warning(status, now=now)

        self.assertTrue(sent)
        send.assert_called_once()
        self.assertEqual(
            reward.config.CoinOverflowWarning_LastNotification,
            now,
        )

    def test_reward_does_not_advance_cooldown_when_send_fails(self):
        now = datetime(2026, 8, 27, 16, 0, 0)
        previous = datetime(2020, 1, 1)
        reward = object.__new__(Reward)
        reward.config = SimpleNamespace(
            config_name='alas2',
            CoinOverflowWarning_Enable=True,
            CoinOverflowWarning_StorageThreshold=0.95,
            CoinOverflowWarning_CooldownHours=12,
            CoinOverflowWarning_LastNotification=previous,
        )
        status = CoinResourceStatus(94000, 94200)

        with patch('module.reward.reward.send_notification', return_value=False):
            sent = reward._coin_overflow_warning(status, now=now)

        self.assertFalse(sent)
        self.assertEqual(
            reward.config.CoinOverflowWarning_LastNotification,
            previous,
        )


if __name__ == '__main__':
    unittest.main()
