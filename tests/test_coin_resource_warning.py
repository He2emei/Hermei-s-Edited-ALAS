import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.reward.coin_resource import (
    COIN_STORAGE_CURRENT,
    COIN_STORAGE_LIMIT,
    CoinResourceStatus,
)
from module.reward.reward import Reward


class CoinResourceStatusTest(unittest.TestCase):
    def test_current_ocr_covers_the_existing_six_digit_main_screen_area(self):
        self.assertEqual(COIN_STORAGE_CURRENT.area, (716, 24, 780, 49))
        self.assertEqual(COIN_STORAGE_LIMIT.area, (716, 0, 780, 22))

    def test_reward_retries_a_truncated_limit_before_using_the_reading(self):
        reward = object.__new__(Reward)
        reward.device = SimpleNamespace(image=object(), screenshot=Mock())
        reward.ui_ensure = Mock()
        reward.ui_goto = Mock()

        readings = [
            (111618, 9200),
            (111618, 94200),
            (111618, 94200),
        ]
        with patch('module.reward.reward.read_coin_storage', side_effect=readings):
            status = reward._coin_resource_status()

        self.assertEqual(status.storage_current, 111618)
        self.assertEqual(status.storage_limit, 94200)
        self.assertEqual(reward.device.screenshot.call_count, 2)

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

        truncated = CoinResourceStatus(
            storage_current=11188,
            storage_limit=9200,
        )
        self.assertFalse(
            truncated.storage_warning_reached(storage_threshold=1.0))

    def test_warning_threshold_is_clamped_to_a_safe_range(self):
        status = CoinResourceStatus(
            storage_current=8000,
            storage_limit=10000,
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
