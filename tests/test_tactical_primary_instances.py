import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.tactical import tactical_class as tactical


class TacticalPrimaryInstanceTest(unittest.TestCase):
    @staticmethod
    def runner():
        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.device = SimpleNamespace(image=object())
        runner.tactical_locked_primary_levels = {}
        return runner

    @staticmethod
    def buttons(count):
        class Card:
            def __init__(self, index):
                self.area = (index, 0, index + 1, 1)

            def crop(self, *args, **kwargs):
                return object()

        return [Card(index) for index in range(count)]

    def choose(self, names, levels, locks, start=0, min_level=1, runner=None):
        runner = runner or self.runner()
        with patch.object(tactical, 'dock_card_lock', side_effect=locks):
            result = runner._tactical_normal_candidate_index(
                self.buttons(len(names)), levels, names, start, min_level
            )
        return runner, result

    def test_max_locked_instance_blocks_lower_locked_copy_after_all_skills_max(self):
        runner, first = self.choose(['德意志', '德意志'], [125, 1], [True, True])
        self.assertEqual(first, 0)
        runner, next_candidate = self.choose(
            ['德意志', '德意志'], [125, 1], [True, True], start=1, runner=runner
        )
        self.assertIsNone(next_candidate)
        self.assertEqual(runner.tactical_locked_primary_levels['德意志'], 125)

    def test_unlocked_higher_instance_does_not_block_lower_locked_candidate(self):
        _, result = self.choose(['德意志', '德意志'], [125, 80], [False, True])
        self.assertEqual(result, 1)

    def test_unknown_and_unlocked_cards_are_skipped(self):
        _, result = self.choose(['未收录舰船', '德意志'], [90, 90], [False])
        self.assertIsNone(result)

    def test_same_highest_instance_can_be_selected_for_another_skill(self):
        runner, first = self.choose(['德意志'], [125], [True])
        runner, second = self.choose(['德意志'], [125], [True], runner=runner)
        self.assertEqual((first, second), (0, 0))

    def test_minimum_level_and_same_page_duplicate_gates_remain(self):
        _, below_minimum = self.choose(['德意志'], [80], [True], min_level=90)
        _, ambiguous = self.choose(['德意志', '德意志'], [90, 90], [True, True])
        self.assertIsNone(below_minimum)
        self.assertIsNone(ambiguous)

    def test_identity_level_card_count_mismatch_fails_closed(self):
        runner = self.runner()
        with patch.object(tactical, 'dock_card_lock') as lock:
            result = runner._tactical_normal_candidate_index(
                self.buttons(2), [100, 90], ['德意志'], 0, 1
            )
        self.assertIsNone(result)
        lock.assert_not_called()

    def test_normal_selection_cursor_advances_from_the_actual_locked_primary(self):
        runner = self.runner()
        runner.config = SimpleNamespace(AddNewStudent_Favorite=False, AddNewStudent_MinLevel=1)
        runner.tactical_priority_names = ()
        runner.tactical_priority_filter_changed = False
        runner.tactical_dock_filters_initialized = True
        runner.tactical_dock_page_count = 1
        runner.tactical_dock_page_fingerprints = set()
        runner.tactical_dock_expect_new_page = False
        runner.dock_select_index = 0
        runner._tactical_select_priority_ship = Mock(return_value=False)
        runner._tactical_restore_priority_filters = Mock()
        runner._tactical_initialize_dock_filters = Mock()
        runner.appear = Mock(return_value=False)
        runner.loop = lambda timeout=1: iter([None])
        runner.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                        screenshot=Mock(), sleep=Mock(), click=Mock())
        runner._tactical_dock_page_fingerprint = Mock(return_value=123)
        runner.dock_select_one = Mock()
        runner.dock_select_confirm = Mock()
        runner.interval_clear = Mock()
        cards = self.buttons(4)
        runner.dock_select_index = 0

        with patch.object(tactical.server, 'server', 'cn'), \
                patch.object(tactical, 'dock_cards', return_value=cards), \
                patch.object(tactical, 'LevelOcr') as level_ocr, \
                patch.object(tactical, 'Ocr') as name_ocr, \
                patch.object(tactical, 'dock_card_lock',
                             side_effect=lambda image, button: button is not cards[0]), \
                patch.object(tactical.DOCK_SCROLL, 'appear', return_value=False):
            level_ocr.return_value.ocr.return_value = [125, 125, 1, 80]
            name_ocr.return_value.ocr.return_value = ['德意志', '德意志', '德意志', '亚利桑那']

            self.assertTrue(runner.select_suitable_ship())
            self.assertIs(runner.dock_select_one.call_args[0][0], cards[1])
            self.assertEqual(runner.dock_select_index, 1)

            self.assertTrue(runner._tactical_advance_ship_candidate())
            self.assertEqual(runner.dock_select_index, 2)

            self.assertTrue(runner.select_suitable_ship())

        self.assertEqual(runner.dock_select_index, 3)
        self.assertIs(runner.dock_select_one.call_args[0][0], cards[3])


if __name__ == '__main__':
    unittest.main()
