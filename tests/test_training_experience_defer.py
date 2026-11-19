"""Replay the Nov19 OCR failure without inventing an EXP number or cap."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import RequestHumanTakeover
from module.os import training_ui as ui
from module.os.training import TrainingFleetManager
from module.os.training_policy import ShipCandidate
from module.os_handler.assets import ORDER_ENTER
from module.ui.assets import BACK_ARROW

ROOT = Path(__file__).parents[1]


class ExperienceOnlyDeferTest(unittest.TestCase):
    def read_recorded(self, names=None, levels=None, locks=None, details=None,
                      fraction=None, empty_stars=False):
        frame = np.asarray(Image.open(
            ROOT / 'tests/fixtures/opsi_training/tiger-105-post-awakening-exp-noise.png'
        ).convert('RGB'))
        inspector = ui.TrainingShipInspector.__new__(ui.TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        index = [-1]
        def screenshot():
            index[0] += 1
        def current(values, default):
            return (values or [default] * 4)[index[0]]
        inspector.device = SimpleNamespace(image=frame, screenshot=screenshot)
        inspector.appear = Mock(side_effect=lambda *a, **k: current(details, True))
        def ocr(buttons, **kwargs):
            name = kwargs.get('name')
            values = {
                'TrainingName': [current(names, '莫加多尔')] * 2,
                'TrainingStoredExpMaxA': '000',
                'TrainingStoredExpMaxB': 'UUU',
                'TrainingStoredExp': fraction or '47624114000',
                'TrainingCurrentExp': fraction or '4762:4T14000',
                'TrainingCurrentExpNarrow': fraction or '47Z62Z41114000',
                'TrainingStoredExpTail': '4000',
            }
            self.assertIn(name, values)
            return SimpleNamespace(ocr=lambda image: values[name])
        with patch.object(ui, 'Ocr', side_effect=ocr), \
                patch.object(ui, 'Digit') as digit, \
                patch.object(ui, 'detail_ship_lock', side_effect=lambda image: current(locks, True)):
            digit.return_value.ocr.side_effect = lambda image: current(levels, 110)
            if empty_stars:
                with patch.object(ui.cv2, 'matchTemplate', return_value=np.zeros((1, 1), dtype=np.float32)):
                    return inspector.read_ship()
            return inspector.read_ship()

    def test_recorded_numeric_failure_defers_without_returning_a_ship(self):
        with self.assertRaises(ui.TrainingExperienceUnavailable) as raised:
            self.read_recorded()
        self.assertNotIsInstance(raised.exception, ui.TrainingStoredExpUnavailable)

    def test_readable_fraction_keeps_normal_exp_semantics(self):
        ship = self.read_recorded(fraction='47624/114000')
        self.assertEqual((ship.name, ship.level, ship.level_cap, ship.stored_exp),
                         ('莫加多尔', 110, 115, None))

    def test_identity_lock_level_page_or_star_uncertainty_still_takes_over(self):
        cases = (
            {'names': ['莫加多尔', '虎', '莫加多尔', '虎']},
            {'names': ['未知舰船'] * 4},
            {'locks': [True, False, True, False]},
            {'locks': [True, None, True, None]},
            {'levels': [110, 115, 110, 115]},
            {'levels': [125] * 4},
            {'details': [True, True, True, False]},
            {'empty_stars': True},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(RequestHumanTakeover) as raised:
                self.read_recorded(**arguments)
            self.assertNotIsInstance(raised.exception, ui.TrainingExperienceUnavailable)

    def test_final_two_complete_metadata_reads_may_follow_an_unknown_frame(self):
        with self.assertRaises(ui.TrainingExperienceUnavailable):
            self.read_recorded(names=['莫加多尔', '未知舰船', '莫加多尔', '莫加多尔'])

    def manager(self, error=None, current=None, map_visible=True):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
            PriorityTraining_Ships='', PriorityTraining_Allow125Awakening=False, cross_set=Mock())
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                          screenshot=Mock(), click=Mock())
        manager._check_cn = Mock(); manager.ui_ensure = Mock()
        manager.inspect_map_fleet = Mock(side_effect=error) if error else Mock(return_value=current)
        manager._available_ships = Mock(side_effect=AssertionError('must not scan'))
        manager.find_candidates = Mock(side_effect=AssertionError('must not select'))
        manager._deploy = Mock(side_effect=AssertionError('must not deploy'))
        manager._awaken_planned_ship = Mock(side_effect=AssertionError('must not awaken'))
        manager.appear = Mock(side_effect=lambda asset, **kwargs:
            map_visible if asset is ORDER_ENTER else asset is ui.EQUIPMENT_OPEN or asset is BACK_ARROW)
        return manager

    def maintain(self, manager, map_visible=True):
        opsi = SimpleNamespace(os_init=Mock(), globe_goto=Mock(), name_to_zone=lambda name: name,
                               is_in_map=Mock(return_value=map_visible))
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard, \
                patch('module.os.training.priority_ship_names', return_value=()), \
                patch('module.os.training.time.time', return_value=1_800_000_000):
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', None)
            return manager.maintain(opsi)

    def test_initial_exp_only_failure_verifies_map_then_schedules_normal_retry(self):
        manager = self.manager(error=ui.TrainingExperienceUnavailable('recorded fraction unreadable'))
        self.assertFalse(self.maintain(manager))
        manager.device.click.assert_called_once_with(BACK_ARROW)
        manager.config.cross_set.assert_called_once_with(
            keys='OpsiHazard1Leveling.OpsiTraining.LastCheck', value=1_800_000_000)
        for action in (manager._available_ships, manager.find_candidates,
                       manager._deploy, manager._awaken_planned_ship):
            action.assert_not_called()

    def test_failed_map_recovery_keeps_takeover_without_advancing_lastcheck(self):
        manager = self.manager(error=ui.TrainingExperienceUnavailable('unreadable'), map_visible=False)
        with self.assertRaises(RequestHumanTakeover):
            self.maintain(manager, map_visible=False)
        manager.config.cross_set.assert_not_called()

    def test_generic_initial_identity_failure_is_not_caught_as_exp(self):
        manager = self.manager(error=RequestHumanTakeover('identity unknown'))
        with self.assertRaisesRegex(RequestHumanTakeover, 'identity unknown'):
            self.maintain(manager)
        manager.device.click.assert_not_called(); manager.config.cross_set.assert_not_called()

    def test_exp_failure_after_awakening_remains_takeover(self):
        current = {i: ShipCandidate(name, '白鹰', 'main' if i < 4 else 'vanguard',
                                    100, True, False, 0, 100, True)
                   for i, name in enumerate(('英仙座', '彩主力甲', '彩主力乙', '伊吹', '彩先锋甲', '彩先锋乙'), 1)}
        manager = self.manager(current=current)
        manager._awaken_planned_ship = Mock(side_effect=ui.TrainingExperienceUnavailable('post-awakening read'))
        with self.assertRaisesRegex(ui.TrainingExperienceUnavailable, 'post-awakening read'):
            self.maintain(manager)
        manager._awaken_planned_ship.assert_called_once()
        manager.device.click.assert_not_called(); manager.config.cross_set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
