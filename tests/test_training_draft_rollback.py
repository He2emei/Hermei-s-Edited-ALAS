import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import numpy as np

from module.exception import RequestHumanTakeover
from module.os import training
from module.os.training import TrainingFleetManager
from module.os_handler.assets import ORDER_ENTER


class TrainingDraftRollbackTest(unittest.TestCase):
    def make_manager(self, selector_states=(True, True, True), map_states=(True, True),
                     observed=None):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.config = SimpleNamespace(PriorityTraining_Ships='')
        clicks = []
        manager.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            click=Mock(side_effect=lambda button: clicks.append(getattr(button, 'name', None))),
            sleep=Mock(), screenshot=Mock(),
        )
        manager.click_names = clicks
        current = {slot: SimpleNamespace(name='ship{}'.format(slot), level=100 + slot,
                                         is_locked=True) for slot in range(1, 7)}
        planned = dict(current)
        planned[2] = SimpleNamespace(name='replacement', level=120, is_locked=True)
        manager.current = current
        manager.planned = planned
        manager._open_selector = Mock()
        manager._fourth_row_y = Mock(return_value=300)
        manager._open_slot = Mock()
        manager._scan_selection = Mock(return_value=object())
        manager._one_ship_selected = Mock(return_value=True)
        manager._cancel_slot = Mock()
        manager._wait = Mock()
        manager._is_selector = Mock(side_effect=selector_states)
        manager._label = Mock(return_value='立刻前往')
        manager.appear = Mock(return_value=True)
        manager._close_selector = Mock(wraps=manager._close_selector)
        manager.inspect_map_fleet = Mock(return_value=current if observed is None else observed)
        opsi = SimpleNamespace(is_in_map=Mock(side_effect=map_states))
        manager.opsi = opsi
        return manager

    def deploy_with_portrait_score(self, manager, score):
        opsi = manager.opsi
        with patch('module.os.training.crop', return_value=np.zeros((48, 50, 3), dtype=np.uint8)), \
                patch('module.os.training.cv2.matchTemplate', return_value=np.array([[score]], dtype=np.float32)):
            return manager._deploy(opsi, manager.current, manager.planned)

    def assert_no_final_deploy(self, manager):
        self.assertNotIn('TRAINING_DEPLOY_CONFIRM', manager.click_names)
        self.assertNotIn('OPSI_TRAINING_DEPLOY_PAID', manager.click_names)
        manager._label.assert_not_called()

    def test_failed_portrait_check_cancels_uncommitted_draft_and_defers_if_full_fleet_matches(self):
        manager = self.make_manager()
        inspected = []
        manager.inspect_map_fleet.side_effect = lambda opsi: inspected.append(tuple(manager.click_names)) or manager.current
        result = self.deploy_with_portrait_score(manager, 0.949)
        self.assertIs(result, False)
        self.assertIn('TRAINING_SHIP_CONFIRM', manager.click_names)
        self.assertIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
        self.assert_no_final_deploy(manager)
        manager._close_selector.assert_called_once_with(manager.opsi)
        self.assertEqual(manager.opsi.is_in_map.call_count, 2)
        self.assertEqual(inspected and len(inspected), 1)
        self.assertEqual(inspected[0][-1], 'TRAINING_SELECTOR_CLOSE')
        manager.device.sleep.assert_any_call(0.3)
        manager.inspect_map_fleet.assert_called_once_with(manager.opsi)

    def test_unknown_or_changing_selector_never_closes_draft(self):
        for states in ((False,), (True, False)):
            with self.subTest(states=states):
                manager = self.make_manager(selector_states=states)
                with self.assertRaises(RequestHumanTakeover):
                    self.deploy_with_portrait_score(manager, 0.949)
                self.assertNotIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
                self.assert_no_final_deploy(manager)
                manager.inspect_map_fleet.assert_not_called()

    def test_unknown_or_changing_map_never_inspects_fleet(self):
        for states in ((False, True), (True, False)):
            with self.subTest(states=states):
                manager = self.make_manager(map_states=states)
                with self.assertRaises(RequestHumanTakeover):
                    self.deploy_with_portrait_score(manager, 0.949)
                self.assertIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
                self.assert_no_final_deploy(manager)
                manager.inspect_map_fleet.assert_not_called()

    def test_changed_incomplete_or_unknown_lock_fleet_remains_takeover(self):
        cases = []
        changed = {slot: ship for slot, ship in self.make_manager().current.items()}
        changed[2] = SimpleNamespace(name='other_ship', level=102, is_locked=True)
        cases.append(('changed ship', changed))
        incomplete = {slot: ship for slot, ship in self.make_manager().current.items() if slot != 6}
        cases.append(('missing slot', incomplete))
        unknown_lock = {slot: ship for slot, ship in self.make_manager().current.items()}
        unknown_lock[2] = SimpleNamespace(name='ship2', level=102, is_locked=None)
        cases.append(('unknown lock', unknown_lock))
        for label, observed in cases:
            with self.subTest(label=label):
                manager = self.make_manager(observed=observed)
                with self.assertRaises(RequestHumanTakeover):
                    self.deploy_with_portrait_score(manager, 0.949)
                self.assertIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
                manager.inspect_map_fleet.assert_called_once_with(manager.opsi)
                self.assert_no_final_deploy(manager)

    def test_order_enter_missing_never_inspects_map_fleet(self):
        manager = self.make_manager()
        manager.appear.return_value = False
        with self.assertRaises(RequestHumanTakeover):
            self.deploy_with_portrait_score(manager, 0.949)
        self.assertIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
        manager.inspect_map_fleet.assert_not_called()
        self.assert_no_final_deploy(manager)

    def test_each_protected_anchor_identity_or_lock_change_takes_over(self):
        for slot in (1, 4):
            for field, value in (('name', 'different'), ('level', 99), ('is_locked', False)):
                with self.subTest(slot=slot, field=field):
                    observed = dict(self.make_manager().current)
                    original = observed[slot]
                    observed[slot] = SimpleNamespace(
                        name=value if field == 'name' else original.name,
                        level=value if field == 'level' else original.level,
                        is_locked=value if field == 'is_locked' else original.is_locked)
                    manager = self.make_manager(observed=observed)
                    with self.assertRaises(RequestHumanTakeover):
                        self.deploy_with_portrait_score(manager, 0.949)
                    manager.inspect_map_fleet.assert_called_once_with(manager.opsi)
                    self.assert_no_final_deploy(manager)

    def test_invalid_original_snapshot_is_rejected_before_selector_close(self):
        cases = []
        unknown_lock = dict(self.make_manager().current)
        unknown_lock[2] = SimpleNamespace(name='ship2', level=102, is_locked=None)
        cases.append(('unknown lock', unknown_lock))
        missing_slot = {slot: ship for slot, ship in self.make_manager().current.items() if slot != 6}
        cases.append(('missing slot', missing_slot))
        illegal_level = dict(self.make_manager().current)
        illegal_level[2] = SimpleNamespace(name='ship2', level=126, is_locked=True)
        cases.append(('level out of range', illegal_level))
        boolean_level = dict(self.make_manager().current)
        boolean_level[2] = SimpleNamespace(name='ship2', level=True, is_locked=True)
        cases.append(('boolean level', boolean_level))
        boolean_key = {True: self.make_manager().current[1]}
        boolean_key.update({slot: self.make_manager().current[slot] for slot in range(2, 7)})
        cases.append(('boolean slot key', boolean_key))
        for label, current in cases:
            with self.subTest(label=label):
                manager = self.make_manager()
                manager.current = current
                with self.assertRaises(RequestHumanTakeover):
                    self.deploy_with_portrait_score(manager, 0.949)
                self.assertNotIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
                manager.inspect_map_fleet.assert_not_called()
                self.assert_no_final_deploy(manager)

    def test_score_at_threshold_does_not_enter_rollback_path(self):
        manager = self.make_manager()
        manager._label.side_effect = AssertionError('expected normal flow to reach native deploy label')
        with self.assertRaisesRegex(AssertionError, 'normal flow'):
            self.deploy_with_portrait_score(manager, 0.96)
        self.assertNotIn('TRAINING_SELECTOR_CLOSE', manager.click_names)
        manager.inspect_map_fleet.assert_not_called()
        manager._label.assert_called_once_with((970, 584, 1155, 621))


if __name__ == '__main__':
    unittest.main()

