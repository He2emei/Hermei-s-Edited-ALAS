import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.exception import RequestHumanTakeover
from module.os import training
from module.os.training import TrainingFleetManager


class CancelSlotTransitionTest(unittest.TestCase):
    def manager(self, mode='lose_once', counts=((0, 0, 1),)):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.state = 'dock'
        manager.frame = 0
        manager.clock = 0.0
        manager.touches = []
        manager.touch_times = []
        manager.unknown_frames = 0
        manager.counts = list(counts)

        def screenshot():
            manager.frame += 1
            if mode == 'selector_gap':
                manager.state = {1: 'selector', 2: 'unknown', 3: 'selector'}.get(
                    manager.frame, 'unknown')
            if mode == 'unknown_then_recover' and manager.state == 'unknown':
                manager.unknown_frames += 1
                if manager.unknown_frames >= 2:
                    manager.state = 'dock'
            if mode == 'late_selector' and manager.touches and manager.frame >= 10:
                manager.state = 'selector'

        def click(button):
            manager.touches.append(button)
            manager.touch_times.append(manager.clock)
            if mode == 'instant_selector':
                manager.state = 'selector'
            elif mode == 'lose_once':
                if len(manager.touches) >= 2:
                    manager.state = 'selector'
            elif mode == 'unknown_then_recover':
                if len(manager.touches) == 1:
                    manager.state = 'unknown'
                else:
                    manager.state = 'selector'
            elif mode == 'unknown_persistent':
                manager.state = 'unknown'

        def sleep(seconds):
            manager.clock += seconds

        manager.device = SimpleNamespace(click=click, screenshot=screenshot, sleep=sleep,
                                          image=object())
        manager._is_selector = lambda: manager.state == 'selector'
        manager.appear = lambda button, **kwargs: button is training.DOCK_CHECK and manager.state == 'dock'
        return manager

    def run_cancel(self, manager, counts=None):
        values = list(manager.counts if counts is None else counts)
        def read(_image):
            if len(values) > 1:
                return values.pop(0)
            return values[0]
        with patch('module.os.training.point_button', side_effect=lambda x, y, name: (x, y, name)), \
                patch.object(training.OCR_DOCK_SELECTED, 'ocr', side_effect=read), \
                patch('module.os.training.time.monotonic', side_effect=lambda: manager.clock):
            return TrainingFleetManager._cancel_slot(manager)

    def test_lost_first_cancel_is_retried_and_recovers_to_selector(self):
        manager = self.manager('lose_once')
        self.assertIsNone(self.run_cancel(manager))
        self.assertEqual(len(manager.touches), 2)
        self.assertEqual(manager.touches, [(808, 670, 'TRAINING_SHIP_CANCEL')] * 2)
        self.assertGreaterEqual(manager.touch_times[1] - manager.touch_times[0], 2.0)

    def test_successful_cancel_is_not_repeated_and_selector_needs_two_frames(self):
        manager = self.manager('instant_selector')
        self.assertIsNone(self.run_cancel(manager))
        self.assertEqual(len(manager.touches), 1)
        self.assertGreaterEqual(manager.frame, 4)  # two stable dock and two stable selector observations

    def test_delayed_selector_does_not_trigger_duplicate_touch(self):
        manager = self.manager('late_selector')
        self.assertIsNone(self.run_cancel(manager))
        self.assertEqual(len(manager.touches), 1)

    def test_retry_limit_is_three_and_each_touch_is_spaced(self):
        manager = self.manager('persistent_failure')
        with self.assertRaises(RequestHumanTakeover):
            self.run_cancel(manager)
        self.assertEqual(len(manager.touches), 3)
        self.assertTrue(all(b - a >= 2.0 for a, b in zip(manager.touch_times, manager.touch_times[1:])))

    def test_unknown_transition_resets_stability_and_never_clicks_blindly(self):
        manager = self.manager('unknown_then_recover')
        self.assertIsNone(self.run_cancel(manager))
        self.assertEqual(len(manager.touches), 2)

    def test_persistent_unknown_page_does_not_repeat_cancel(self):
        manager = self.manager('unknown_persistent')
        with self.assertRaises(RequestHumanTakeover):
            self.run_cancel(manager)
        self.assertEqual(len(manager.touches), 1)

    def test_only_stable_zero_or_one_of_one_count_allows_cancel(self):
        for current in (0, 1):
            with self.subTest(current=current):
                manager = self.manager('instant_selector', counts=((current, 0, 1),))
                self.assertIsNone(self.run_cancel(manager))
                self.assertEqual(len(manager.touches), 1)

    def test_invalid_or_changing_count_never_allows_cancel(self):
        cases = (((True, 0, 1),), ((0, 0, True),), ((0, 0, 2),),
                 ((0, 0, 1), (1, 0, 1), (True, 0, 1)))
        for counts in cases:
            with self.subTest(counts=counts):
                manager = self.manager('persistent_failure', counts=counts)
                with self.assertRaises(RequestHumanTakeover):
                    self.run_cancel(manager)
                self.assertEqual(manager.touches, [])

    def test_stable_selector_at_entry_is_success_without_click(self):
        manager = self.manager('persistent_failure')
        manager.state = 'selector'
        self.assertIsNone(self.run_cancel(manager))
        self.assertEqual(manager.touches, [])

    def test_selector_frames_separated_by_unknown_are_not_stable_success(self):
        manager = self.manager('selector_gap')
        with self.assertRaises(RequestHumanTakeover):
            self.run_cancel(manager)
        self.assertEqual(manager.touches, [])

    def test_contradictory_selector_and_dock_page_times_out_without_touch(self):
        manager = self.manager('persistent_failure')
        manager._is_selector = lambda: True
        manager.appear = lambda button, **kwargs: button is training.DOCK_CHECK
        with self.assertRaises(RequestHumanTakeover):
            self.run_cancel(manager)
        self.assertEqual(manager.touches, [])


if __name__ == '__main__':
    unittest.main()
