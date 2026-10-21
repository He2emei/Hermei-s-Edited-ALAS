import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from module.base.button import Button
from module.exception import RequestHumanTakeover
from module.os.training_policy import PolicyDecision, ShipCandidate
from module.os.training_ui import TrainingShipInspector


class EndOfDock:
    edge_threshold = 0.05

    def set_top(self, main):
        pass

    def cal_position(self, main):
        return 1.0


class TrainingCandidateInstanceTest(unittest.TestCase):
    def scan(self, rows, details=(), decision=None):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = lambda *args, **kwargs: None
        inspector.dock_favourite_set = lambda *args, **kwargs: None
        inspector.dock_sort_method_dsc_set = lambda *args, **kwargs: None
        filter_calls = []
        inspector.dock_filter_set = lambda **kwargs: filter_calls.append(kwargs)
        inspector.ship_info_enter = lambda *args, **kwargs: None
        inspector.wait_until_appear = lambda *args, **kwargs: True
        inspector.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                           screenshot=lambda: None, click=lambda *args, **kwargs: None,
                                           sleep=lambda *args, **kwargs: None,
                                           click_record_clear=lambda: None)
        inspector.appear = lambda *args, **kwargs: False
        detail_iter = iter(details)

        def read_ship():
            value = next(detail_iter)
            if isinstance(value, Exception):
                raise value
            return value

        inspector.read_ship = read_ship
        cards = [Button((10 + i * 30, 10, 30 + i * 30, 30), (0, 0, 0),
                        (10 + i * 30, 10, 30 + i * 30, 30), name=f'card-{i}')
                 for i in range(len(rows))]
        levels = [row[1] for row in rows]
        names = [row[0] for row in rows]
        locks = [row[2] for row in rows]
        with patch('module.os.training_ui.DOCK_SCROLL.set_top'), \
                patch('module.os.training_ui.dock_cards', return_value=cards), \
                patch('module.os.training_ui.dock_card_lock', side_effect=locks), \
                patch('module.os.training_ui.LevelOcr') as level_ocr, \
                patch('module.os.training_ui.Ocr') as ocr:
            level_ocr.return_value.ocr.return_value = levels
            ocr.return_value.ocr.return_value = names
            found = inspector.find_candidates(
                'submarine', frozenset(), set(), needed=99, scroll=EndOfDock(),
                decide_candidate=decision)
        return found, filter_calls

    @staticmethod
    def candidate(name, level, stored=0, cap=120, locked=True):
        return ShipCandidate(name, '铁血', 'submarine', level, False, True,
                             stored, cap, locked)

    def test_locked_125_skips_details_and_blocks_lower_locked_copy(self):
        found, filters = self.scan(
            [('德意志', 125, True), ('德意志', 80, True)],
            details=[self.candidate('德意志', 80)])
        self.assertEqual(found, [])
        self.assertEqual(filters[0]['sort'], 'level')

    def test_dorm_callback_blocks_120_and_keeps_110_full_xp_instance(self):
        for level, stored, cap in ((120, 0, 120), (110, 3_000_000, 110)):
            with self.subTest(level=level):
                found, _ = self.scan(
                    [('德意志', level, True), ('德意志', 80, True)],
                    details=[self.candidate('德意志', level, stored, cap)],
                    decision=lambda ship: PolicyDecision(ship.level < 120, 'dorm policy'))
                self.assertEqual(found, [] if level == 120 else [self.candidate('德意志', level, stored, cap)])

    def test_unlocked_highest_does_not_block_lower_locked_instance(self):
        lower = self.candidate('德意志', 80, cap=100)
        found, _ = self.scan(
            [('德意志', 125, False), ('德意志', 80, True)], details=[lower])
        self.assertEqual(found, [lower])

    def test_unreadable_highest_locked_instance_does_not_fall_back(self):
        found, _ = self.scan(
            [('德意志', 110, True), ('德意志', 80, True)],
            details=[RequestHumanTakeover('fixture unreadable'), self.candidate('德意志', 80)])
        self.assertEqual(found, [])

    def test_without_callback_uses_shared_trainability(self):
        candidate = self.candidate('德意志', 110, 3_000_000, 110)
        found, _ = self.scan([('德意志', 110, True)], details=[candidate])
        self.assertEqual(found, [])

    def test_callback_can_accept_110_with_full_stored_exp(self):
        candidate = self.candidate('德意志', 110, 3_000_000, 110)
        found, _ = self.scan(
            [('德意志', 110, True)], details=[candidate],
            decision=lambda ship: PolicyDecision(True, 'dorm-specific'))
        self.assertEqual(found, [candidate])


if __name__ == '__main__':
    unittest.main()
