import csv
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import cv2
import numpy as np

from module.statistics import gem_ledger


class GemLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 21, 23, 50, tzinfo=timezone(timedelta(hours=8)))

    def rows(self, profile):
        with open(os.path.join(self.temp.name, profile + '-gems-daily.csv'),
                  newline='', encoding='utf-8') as stream:
            return list(csv.DictReader(stream))

    def test_real_supported_home_ocr_reads_1058(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'gem_ledger',
                               'alas-post-manual-supported-home.png')
        image = cv2.imread(fixture)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        with patch.object(gem_ledger, 'record_balance', return_value=True) as record:
            self.assertTrue(gem_ledger.record_home_frames(
                'alas', [image, image, image], data_dir=self.temp.name))
        self.assertEqual(record.call_args[0][1], 1058)

    def test_zero_is_valid_and_blank_is_not_zero(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(gem_ledger.GEM_BALANCE_OCR, 'ocr', return_value='0'):
            self.assertEqual(gem_ledger._ocr_balance(image), 0)
        with patch.object(gem_ledger.GEM_BALANCE_OCR, 'ocr', return_value=''):
            self.assertIsNone(gem_ledger._ocr_balance(image))
        with patch.object(gem_ledger.GEM_BALANCE_OCR, 'ocr', return_value='  '):
            self.assertIsNone(gem_ledger._ocr_balance(image))

    def test_two_consistent_frames_are_required(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(gem_ledger, '_ocr_balance', side_effect=[8000, 8000, None]):
            self.assertTrue(gem_ledger.record_home_frames(
                'alas2', [image] * 3, self.now, data_dir=self.temp.name))
        with patch.object(gem_ledger, '_ocr_balance', side_effect=[8000, None, 9000]):
            self.assertFalse(gem_ledger.record_home_frames(
                'alas2', [image] * 3, self.now + timedelta(minutes=1), data_dir=self.temp.name))

    def test_profiles_persist_independently_and_export_daily_net_with_gaps(self):
        self.assertTrue(gem_ledger.record_balance('alas', 100, self.now, data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance(
            'alas2', 8000, self.now, source='manual_seed', evidence='verified screenshot',
            data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance(
            'alas', 120, self.now + timedelta(days=3), data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance(
            'alas', 90, self.now + timedelta(days=1), data_dir=self.temp.name))
        rows = self.rows('alas')
        self.assertEqual([row['date'] for row in rows], ['2026-10-21', '2026-10-22', '2026-10-24'])
        self.assertEqual(rows[0]['net_change'], '')
        self.assertEqual(rows[1]['net_change'], '-10')
        self.assertEqual(rows[2]['net_change'], '30')
        self.assertEqual(rows[2]['gap_days'], '2')
        self.assertEqual(rows[2]['previous_date'], '2026-10-22')
        self.assertEqual(self.rows('alas2')[0]['last'], '8000')

    def test_midnight_groups_by_china_date_and_duplicates_are_ignored(self):
        before = datetime(2026, 10, 21, 23, 59, tzinfo=timezone(timedelta(hours=8)))
        after = datetime(2026, 10, 22, 0, 1, tzinfo=timezone(timedelta(hours=8)))
        self.assertTrue(gem_ledger.record_balance('alas', 1, before, data_dir=self.temp.name))
        self.assertFalse(gem_ledger.record_balance('alas', 9, before, data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance('alas', 2, after, data_dir=self.temp.name))
        rows = self.rows('alas')
        self.assertEqual([row['date'] for row in rows], ['2026-10-21', '2026-10-22'])
        self.assertEqual(rows[0]['last'], '1')

    def test_same_day_summary_uses_timestamp_order(self):
        midday = datetime(2026, 10, 21, 12, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertTrue(gem_ledger.record_balance(
            'alas', 20, midday + timedelta(hours=2), data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance(
            'alas', 10, midday, data_dir=self.temp.name))
        self.assertTrue(gem_ledger.record_balance(
            'alas', 30, midday + timedelta(hours=1), data_dir=self.temp.name))
        row = self.rows('alas')[0]
        self.assertEqual((row['first'], row['last']), ('10', '20'))
        self.assertEqual((row['min'], row['max'], row['samples']), ('10', '30', '3'))

    def test_export_failure_keeps_db_observation_and_duplicate_rebuilds_csv(self):
        with patch.object(gem_ledger, '_atomic_csv', side_effect=OSError('disk full')):
            self.assertTrue(gem_ledger.record_balance(
                'alas', 1234, self.now, data_dir=self.temp.name))
        csv_path = os.path.join(self.temp.name, 'alas-gems-daily.csv')
        self.assertFalse(os.path.exists(csv_path))
        self.assertFalse(gem_ledger.record_balance(
            'alas', 9999, self.now, data_dir=self.temp.name))
        row = self.rows('alas')[0]
        self.assertEqual((row['first'], row['last'], row['samples']), ('1234', '1234', '1'))

    def test_home_sampling_catches_database_errors(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(gem_ledger, '_ocr_balance', side_effect=[5, 5, None]), \
                patch.object(gem_ledger, 'record_balance', side_effect=OSError('disk full')):
            self.assertFalse(gem_ledger.record_home_frames(
                'alas', [image] * 3, data_dir=self.temp.name))

    def test_failed_ledger_write_does_not_interrupt_reward_status(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from module.reward.reward import Reward
        reward = object.__new__(Reward)
        reward.config = SimpleNamespace(config_name='alas')
        reward.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), screenshot=Mock())
        reward.ui_ensure = Mock()
        reward.ui_page_appear = Mock(return_value=True)
        reward.ui_goto = Mock()
        with patch('module.config.server.server', 'cn'), \
                patch('module.reward.reward.read_coin_storage', return_value=(1, 10000)), \
                patch('module.reward.reward.record_home_frames', side_effect=OSError('disk full')):
            status = reward._coin_resource_status()
        self.assertEqual(status.storage_current, 1)
        self.assertEqual(reward.device.screenshot.call_count, 2)


if __name__ == '__main__':
    unittest.main()
