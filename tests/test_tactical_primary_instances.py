import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
        return [SimpleNamespace(area=(index, 0, index + 1, 1)) for index in range(count)]

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


if __name__ == '__main__':
    unittest.main()
