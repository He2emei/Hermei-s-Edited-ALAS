import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from module.exception import RequestHumanTakeover
from module.hard.selection import select_hard_stage
from module.reward.exp_books import check_exp_book_warning


class HardSelectionTest(unittest.TestCase):
    def test_selects_lowest_inventory_and_keeps_chapter(self):
        self.assertEqual(
            select_hard_stage('11-4', {
                'destroyer': 8, 'cruiser': 2, 'battleship': 5, 'carrier': 9,
            }),
            '11-2',
        )

    def test_configured_map_wins_a_tie(self):
        counts = {key: 4 for key in ('destroyer', 'cruiser', 'battleship', 'carrier')}
        self.assertEqual(select_hard_stage('7-3', counts), '7-3')

    def test_chapters_before_three_are_rejected(self):
        with self.assertRaises(RequestHumanTakeover):
            select_hard_stage('2-4', {
                'destroyer': 1, 'cruiser': 1, 'battleship': 1, 'carrier': 1,
            })

    def test_unknown_inventory_is_rejected(self):
        with self.assertRaises(RequestHumanTakeover):
            select_hard_stage('3-1', {'destroyer': 0})


class ExperienceBookWarningTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 10, 12, 0)
        self.config = SimpleNamespace(
            config_name='alas',
            ExpBookWarning_Enable=True,
            ExpBookWarning_Threshold=2900,
            ExpBookWarning_LastCheck=datetime(2020, 1, 1),
            ExpBookWarning_LastCount=-1,
            ExpBookWarning_LastNotification=datetime(2020, 1, 1),
        )
        self.device = object()

    def _reader(self, counts):
        class Reader:
            def __init__(self, config, device):
                pass

            def read_counts(self, keys):
                return counts

        return Reader

    def test_reads_once_and_warns_strictly_above_threshold(self):
        storage = types.ModuleType('module.storage.training_inventory')
        storage.TrainingInventory = self._reader({'exp_book_t1': 2901})
        with patch.dict(sys.modules, {'module.storage.training_inventory': storage}), \
                patch('module.reward.exp_books.send_notification', return_value=True) as notify:
            self.assertTrue(check_exp_book_warning(self.config, self.device, self.now))
            self.assertFalse(check_exp_book_warning(self.config, self.device, self.now))
        notify.assert_called_once()
        self.assertEqual(self.config.ExpBookWarning_LastCount, 2901)
        self.assertEqual(self.config.ExpBookWarning_LastNotification, self.now)

    def test_notification_failure_keeps_daily_retry_possible(self):
        storage = types.ModuleType('module.storage.training_inventory')
        storage.TrainingInventory = self._reader({'exp_book_t1': 3000})
        with patch.dict(sys.modules, {'module.storage.training_inventory': storage}), \
                patch('module.reward.exp_books.send_notification', return_value=False) as notify:
            self.assertFalse(check_exp_book_warning(self.config, self.device, self.now))
            self.assertFalse(check_exp_book_warning(self.config, self.device, self.now))
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(self.config.ExpBookWarning_LastCheck, self.now)
        self.assertEqual(self.config.ExpBookWarning_LastNotification, datetime(2020, 1, 1))

    def test_read_failure_does_not_mark_success(self):
        storage = types.ModuleType('module.storage.training_inventory')
        storage.TrainingInventory = self._reader({})
        with patch.dict(sys.modules, {'module.storage.training_inventory': storage}):
            self.assertFalse(check_exp_book_warning(self.config, self.device, self.now))
        self.assertEqual(self.config.ExpBookWarning_LastCheck, datetime(2020, 1, 1))
        self.assertEqual(self.config.ExpBookWarning_LastCount, -1)


if __name__ == '__main__':
    unittest.main()
