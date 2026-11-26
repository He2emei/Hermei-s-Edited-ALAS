from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.exception import RequestHumanTakeover
from module.os.training import DeploymentTargetUnavailable, TrainingFleetManager
from module.os.training_policy import ShipCandidate


class TrainingPreflightUnavailableTest(unittest.TestCase):
    def manager(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                         screenshot=Mock(), click=Mock(), sleep=Mock())
        manager.appear = Mock(return_value=True)
        manager._open_selector = Mock()
        manager._fourth_row_y = Mock(return_value=300)
        manager._is_priority_ur = Mock(return_value=False)
        manager._open_slot = Mock()
        manager._cancel_slot = Mock()
        manager._close_selector = Mock()
        manager._one_ship_selected = Mock(return_value=True)
        return manager

    @staticmethod
    def fleets():
        current_ship = SimpleNamespace(name='原舰', level=100, is_locked=True)
        planned_ship = ShipCandidate('目标', '白鹰', 'vanguard', 80, False, True, None, 100, True)
        return {2: current_ship}, {2: planned_ship}

    def test_missing_target_before_any_draft_cancels_and_defers_on_two_zero_checks(self):
        manager = self.manager()
        current, planned = self.fleets()
        manager._scan_selection = Mock(side_effect=DeploymentTargetUnavailable('missing'))
        with patch('module.os.training.ROTATION_SLOTS', (2,)), patch(
                'module.os.training.OCR_DOCK_SELECTED.ocr', side_effect=[(0, 1, 1), (0, 1, 1)]) as count:
            result = manager._deploy(object(), current, planned)
        self.assertIs(result, False)
        self.assertEqual(manager.device.screenshot.call_count, 2)
        manager.device.sleep.assert_called_once_with(0.3)
        self.assertEqual(count.call_count, 2)
        manager._cancel_slot.assert_called_once_with()
        manager._close_selector.assert_called_once()
        manager.device.click.assert_not_called()

    def test_selected_one_bool_or_unknown_page_counter_propagates(self):
        manager = self.manager()
        current, planned = self.fleets()
        manager._scan_selection = Mock(side_effect=DeploymentTargetUnavailable('missing'))
        for page_ok, counts, message in (
                (True, [(1, 1, 1), (1, 1, 1)], 'selection count'),
                (True, [(True, 1, 1), (True, 1, 1)], 'selection count'),
                (True, [(0, 1, True), (0, 1, True)], 'selection count'),
                (False, [(0, 1, 1), (0, 1, 1)], 'unknown deployment dock'),
                (True, [(2, 1, 1), (2, 1, 1)], 'selection count'),
                (True, [(0, 1, 1), (1, 1, 1)], 'selection count')):
            manager = self.manager()
            manager.appear = Mock(return_value=page_ok)
            manager._scan_selection = Mock(side_effect=DeploymentTargetUnavailable('missing'))
            with patch('module.os.training.ROTATION_SLOTS', (2,)), patch(
                    'module.os.training.OCR_DOCK_SELECTED.ocr', side_effect=counts):
                with self.assertRaisesRegex(RequestHumanTakeover, message):
                    manager._deploy(object(), current, planned)
            manager._cancel_slot.assert_not_called()
            manager._close_selector.assert_not_called()

    def test_cancel_or_close_failure_propagates_without_returning_false(self):
        current, planned = self.fleets()
        for failing_action in ('cancel', 'close'):
            manager = self.manager()
            manager._scan_selection = Mock(side_effect=DeploymentTargetUnavailable('missing'))
            if failing_action == 'cancel':
                manager._cancel_slot.side_effect = RequestHumanTakeover('cancel failed')
            else:
                manager._close_selector.side_effect = RequestHumanTakeover('close failed')
            with patch('module.os.training.ROTATION_SLOTS', (2,)), patch(
                    'module.os.training.OCR_DOCK_SELECTED.ocr', side_effect=[(0, 1, 1), (0, 1, 1)]):
                with self.assertRaisesRegex(RequestHumanTakeover, failing_action + ' failed'):
                    manager._deploy(object(), current, planned)

    def test_general_takeover_is_not_converted_to_defer(self):
        manager = self.manager()
        current, planned = self.fleets()
        manager._scan_selection = Mock(side_effect=RequestHumanTakeover('unknown geometry'))
        with patch('module.os.training.ROTATION_SLOTS', (2,)):
            with self.assertRaisesRegex(RequestHumanTakeover, 'unknown geometry'):
                manager._deploy(object(), current, planned)
        manager._cancel_slot.assert_not_called()
        manager._close_selector.assert_not_called()

    def test_target_unavailable_during_draft_phase_is_not_swallowed(self):
        manager = self.manager()
        current, planned = self.fleets()
        manager._scan_selection = Mock(side_effect=[object(), DeploymentTargetUnavailable('missing')])
        with patch('module.os.training.ROTATION_SLOTS', (2,)), patch(
                'module.os.training.OCR_DOCK_SELECTED.ocr', return_value=(1, 1, 1)):
            with self.assertRaisesRegex(DeploymentTargetUnavailable, 'missing'):
                manager._deploy(object(), current, planned)
        manager._cancel_slot.assert_called_once_with()
        manager._close_selector.assert_not_called()


if __name__ == '__main__':
    unittest.main()

