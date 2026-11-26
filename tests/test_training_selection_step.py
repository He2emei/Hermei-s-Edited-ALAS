import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from module.base.button import Button
from module.exception import RequestHumanTakeover
from module.os.training import DeploymentTargetUnavailable, TrainingFleetManager
from module.os.training_policy import ShipCandidate


class NarrowBandScroll:
    edge_threshold = 0.05

    def __init__(self):
        self.position = 0.0
        self.pages = []
        self.visited = []

    def set_top(self, main):
        self.position = 0.0

    def cal_position(self, main):
        return self.position

    def next_page(self, main, page=0.45):
        self.pages.append(page)
        self.position = min(1.0, self.position + (0.16 if page == 0.45 else 0.08))


class TrainingSelectionStepTest(unittest.TestCase):
    TARGET = ShipCandidate('麦考尔', '白鹰', 'vanguard', 80, False, True, None, 100, True)

    def manager(self, scroll, target_positions=(), unlocked_positions=()):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager._unlocked_positions = tuple(unlocked_positions)
        manager.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            screenshot=lambda: None,
            sleep=lambda seconds: None,
            click_record_clear=lambda: None,
        )
        manager._visible_names = lambda: self.visible(manager, scroll, target_positions,
                                                       unlocked_positions)
        manager._deployment_card_levels = lambda cards: [80]
        return manager

    @staticmethod
    def visible(manager, scroll, target_positions, unlocked_positions):
        position = scroll.position
        scroll.visited.append(position)
        card = Button((10, 10, 150, 70), (0, 0, 0), (10, 10, 150, 70), name='麦考尔-card')
        manager._visible_cards = [card]
        manager._raw_names = ['麦考尔' if any(abs(position - p) < 0.001 for p in target_positions)
                              else '其他-{:.2f}'.format(position)]
        return list(manager._raw_names)

    def scan(self, manager, scroll, target):
        locks = lambda image, button: not any(abs(scroll.position - p) < 0.001
                                             for p in manager._unlocked_positions)
        with patch('module.os.training.DOCK_SCROLL', scroll), \
                patch('module.os.training.dock_card_lock', side_effect=locks), \
                patch('module.os.training.same_card_portrait', return_value=False):
            return manager._scan_selection(target)

    def test_target_scan_uses_fine_step_and_completes_uniqueness_before_relocating(self):
        scroll = NarrowBandScroll()
        manager = self.manager(scroll, target_positions=(0.08,))
        scan_end_positions = []
        scan_positions = []
        relocate = manager._locate_verified_locked_card

        def record_relocation(target):
            scan_end_positions.append(scroll.position)
            scan_positions.extend(scroll.visited)
            return relocate(target)
        manager._locate_verified_locked_card = record_relocation

        selected = self.scan(manager, scroll, self.TARGET)
        self.assertEqual(selected.name, '麦考尔-card')
        # First pass ran to the dock bottom; only then did the locator reset and
        # find the unique verified locked candidate on the narrow 0.08 band.
        self.assertEqual(len(scan_end_positions), 1)
        self.assertGreater(scan_end_positions[0], 0.95)
        self.assertIn(0.08, scan_positions)
        self.assertTrue(all(page == 0.2 for page in scroll.pages))

    def test_coarse_step_reproduces_missing_band_then_fine_step_captures_it(self):
        coarse = NarrowBandScroll()
        coarse_manager = self.manager(coarse, target_positions=(0.08,))
        # Model the pre-change target branch explicitly: every sweep uses .45.
        with patch('module.os.training.DOCK_SCROLL', coarse), \
                patch('module.os.training.dock_card_lock', return_value=True), \
                patch('module.os.training.same_card_portrait', return_value=False):
            original_next_page = coarse.next_page
            coarse.next_page = lambda main, page=0.45: original_next_page(main, page=0.45)
            with self.assertRaisesRegex(RequestHumanTakeover, 'not available'):
                coarse_manager._scan_selection(self.TARGET)
        self.assertEqual(coarse.pages[0], 0.45)
        self.assertNotIn(0.08, coarse.visited)

        fine = NarrowBandScroll()
        fine_manager = self.manager(fine, target_positions=(0.08,))
        selected = self.scan(fine_manager, fine, self.TARGET)
        self.assertEqual(selected.name, '麦考尔-card')

    def test_broad_name_scan_keeps_coarse_step(self):
        scroll = NarrowBandScroll()
        manager = self.manager(scroll)
        with patch('module.os.training.DOCK_SCROLL', scroll):
            names = manager._scan_selection()
        self.assertIn('其他-0.00', names)
        self.assertTrue(scroll.pages)
        self.assertTrue(all(page == 0.45 for page in scroll.pages))


    def test_repeated_ocr_page_with_measured_scroll_progress_scans_to_end(self):
        scroll = NarrowBandScroll()
        manager = self.manager(scroll)
        card = Button((10, 10, 150, 70), (0, 0, 0), (10, 10, 150, 70), name='麦考尔-card')

        def repeated_visible():
            scroll.visited.append(scroll.position)
            manager._visible_cards = [card]
            manager._raw_names = [self.TARGET.name]
            return [self.TARGET.name]

        manager._visible_names = repeated_visible
        manager._deployment_card_levels = lambda cards: [80]
        manager._locate_verified_locked_card = lambda target: Button(
            (1, 1, 2, 2), (0, 0, 0), (1, 1, 2, 2), name='relocated')
        with patch('module.os.training.DOCK_SCROLL', scroll), \
                patch('module.os.training.dock_card_lock', return_value=True), \
                patch('module.os.training.same_card_portrait', return_value=True):
            selected = manager._scan_selection(self.TARGET)
        self.assertEqual(selected.name, 'relocated')
        self.assertGreater(len(scroll.visited), 10)
        self.assertGreater(scroll.visited[-1], 0.95)

    def test_repeated_page_without_scroll_progress_still_stops(self):
        scroll = NarrowBandScroll()
        scroll.next_page = lambda main, page=0.45: scroll.pages.append(page)
        manager = self.manager(scroll)
        manager._raw_names = ['same']
        manager._visible_names = lambda: self.visible(manager, scroll, (), ())
        # Force identical OCR and no scrollbar movement.
        manager._visible_names = lambda: self._same_reading(manager, scroll)
        with patch('module.os.training.DOCK_SCROLL', scroll):
            names = manager._scan_selection()
        self.assertIn('same', names)
        self.assertLessEqual(len(scroll.visited), 2)
        self.assertEqual(len(scroll.pages), 1)

    @staticmethod
    def _same_reading(manager, scroll):
        scroll.visited.append(scroll.position)
        manager._visible_cards = [Button((10, 10, 150, 70), (0, 0, 0), (10, 10, 150, 70))]
        manager._raw_names = ['same']
        return ['same']

    def test_missing_unlocked_or_duplicate_targets_remain_rejected(self):
        missing_scroll = NarrowBandScroll()
        missing_manager = self.manager(missing_scroll)
        with self.assertRaisesRegex(DeploymentTargetUnavailable, 'not available'):
            self.scan(missing_manager, missing_scroll, self.TARGET)

        duplicate_scroll = NarrowBandScroll()
        duplicate_manager = self.manager(duplicate_scroll, target_positions=(0.16, 0.32))
        with self.assertRaisesRegex(RequestHumanTakeover, 'Ambiguous duplicate'):
            self.scan(duplicate_manager, duplicate_scroll, self.TARGET)

        unlocked_scroll = NarrowBandScroll()
        unlocked_manager = self.manager(unlocked_scroll, target_positions=(0.16,),
                                        unlocked_positions=(0.16,))
        with self.assertRaisesRegex(RequestHumanTakeover, 'not available'):
            self.scan(unlocked_manager, unlocked_scroll, self.TARGET)


if __name__ == '__main__':
    unittest.main()
