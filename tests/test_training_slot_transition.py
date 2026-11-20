import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import RequestHumanTakeover
from module.os.training import TrainingFleetManager


class SlotTransitionTest(unittest.TestCase):
    def manager(self, mode):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.state = 'selector'
        manager.mode = mode
        manager.touches = []
        manager.clock = 0.0
        manager.screenshot_count = 0
        manager.touch_times = []
        manager.sleep_calls = []

        def click(point):
            manager.touches.append(point)
            manager.touch_times.append(manager.clock)
            if mode == 'drop_first' and len(manager.touches) == 1:
                return
            if mode == 'persistent_failure':
                return
            if mode in ('unknown', 'unknown_then_dock'):
                manager.state = 'unknown'
            else:
                manager.state = 'dock'

        def screenshot():
            manager.screenshot_count += 1
            if mode == 'unknown_then_dock' and manager.screenshot_count == 2:
                manager.state = 'dock'

        def sleep(seconds):
            manager.sleep_calls.append(seconds)
            manager.clock += seconds

        manager.device = SimpleNamespace(
            click=click, screenshot=screenshot, sleep=sleep)
        manager.appear = lambda button, **kwargs: manager.state == 'dock'
        manager._is_selector = lambda: manager.state == 'selector'
        manager._fourth_row_y = Mock(return_value=336)
        manager.dock_favourite_set = Mock()
        manager.dock_sort_method_dsc_set = Mock()
        manager.dock_filter_set = Mock()
        return manager

    def open(self, manager):
        with patch('module.os.training.point_button', side_effect=lambda x, y, name: (x, y, name)), \
                patch('module.os.training.DOCK_SCROLL.set_top') as set_top, \
                patch('module.os.training.time.monotonic', side_effect=lambda: manager.clock):
            TrainingFleetManager._open_slot(manager, 2)
        return set_top

    def test_dropped_first_touch_retries_only_after_stable_selector(self):
        manager = self.manager('drop_first')
        self.open(manager)
        self.assertEqual(len(manager.touches), 2)
        self.assertEqual(manager.touches, [(517, 336, 'TRAINING_SLOT_2')] * 2)
        manager.dock_filter_set.assert_called_once()

    def test_retry_uses_reacquired_stable_row_location(self):
        manager = self.manager('drop_first')
        row_positions = iter((336, 337, 337))
        manager._fourth_row_y = Mock(side_effect=lambda: next(row_positions, 337))
        self.open(manager)
        self.assertEqual(manager.touches, [
            (517, 336, 'TRAINING_SLOT_2'),
            (517, 337, 'TRAINING_SLOT_2'),
        ])

    def test_successful_first_touch_is_not_repeated(self):
        manager = self.manager('success')
        self.open(manager)
        self.assertEqual(len(manager.touches), 1)

    def test_persistent_failed_touch_is_bounded(self):
        manager = self.manager('persistent_failure')
        with self.assertRaises(RequestHumanTakeover):
            self.open(manager)
        self.assertEqual(len(manager.touches), 3)
        self.assertTrue(all(later - earlier >= 2.0
                            for earlier, later in zip(manager.touch_times, manager.touch_times[1:])))
        manager.dock_filter_set.assert_not_called()

    def test_unknown_transition_can_settle_to_dock_without_another_touch(self):
        manager = self.manager('unknown_then_dock')
        self.open(manager)
        self.assertEqual(len(manager.touches), 1)
        manager.dock_filter_set.assert_called_once()

    def test_unknown_page_is_not_blindly_retried(self):
        manager = self.manager('unknown')
        with self.assertRaises(RequestHumanTakeover):
            self.open(manager)
        self.assertEqual(len(manager.touches), 1)
        manager.dock_filter_set.assert_not_called()

    def test_dock_must_remain_positive_after_point_six_second_interval(self):
        manager = self.manager('success')
        self.open(manager)
        self.assertIn(0.6, manager.sleep_calls)
        self.assertEqual(len(manager.touches), 1)

    def test_immutable_slots_are_rejected(self):
        manager = self.manager('success')
        with patch('module.os.training.point_button') as point_button:
            for slot in (1, 4):
                with self.subTest(slot=slot), self.assertRaises(RequestHumanTakeover):
                    TrainingFleetManager._open_slot(manager, slot)
        self.assertEqual(manager.touches, [])
        point_button.assert_not_called()


if __name__ == '__main__':
    unittest.main()
