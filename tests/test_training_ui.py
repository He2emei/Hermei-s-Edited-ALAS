import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from module.exception import RequestHumanTakeover
from module.os import training_ui
from module.os.training_policy import ShipCandidate, TrainingRequirement
from module.os.training_ui import (
    CATALOG,
    FACTIONS,
    FILTER_FACTIONS,
    TrainingShipInspector,
    catalog_name,
    protected_fleet_anchors,
    validate_protected_fleet,
)
from module.os.training import TrainingFleetManager


ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT.parent / 'code_workflow' / 'evidence' / '2026-09-08'


def candidate(name, faction='白鹰', position='main', level=90, cap=None):
    return ShipCandidate(name, faction, position, level, False, True, None, cap)


class TrainingUiReviewTest(unittest.TestCase):
    def test_fleet_inspection_rejects_non_map_overlay_before_switching(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.appear = lambda *args, **kwargs: False
        opsi = SimpleNamespace(is_in_map=lambda: True,
                               fleet_set=lambda *args: self.fail('must not click fleet control'))
        with self.assertRaisesRegex(RequestHumanTakeover, 'visible OpSi map controls'):
            inspector.inspect_map_fleet(opsi)

    def test_protected_fleet_defaults_preserve_existing_anchors(self):
        self.assertEqual(
            protected_fleet_anchors(SimpleNamespace()),
            ('英仙座', '伊吹'),
        )

    def test_configured_protected_fleet_accepts_catalogued_position_matched_ships(self):
        config = SimpleNamespace(
            OpsiTraining_ProtectedMainShip='英仙座',
            OpsiTraining_ProtectedVanguardShip='普利茅斯',
        )
        ships = {
            1: candidate('英仙座'),
            4: candidate('普利茅斯', position='vanguard'),
        }
        validate_protected_fleet(ships, config)

    def test_protected_fleet_rejects_unknown_or_position_mismatched_config(self):
        ships = {1: candidate('英仙座'), 4: candidate('伊吹', position='vanguard')}
        for main_name, vanguard_name in (
                ('', '伊吹'), ('未知舰船', '伊吹'), ('企业', '企业'), ('英仙座', '企业')):
            config = SimpleNamespace(
                OpsiTraining_ProtectedMainShip=main_name,
                OpsiTraining_ProtectedVanguardShip=vanguard_name,
            )
            with self.subTest(main=main_name, vanguard=vanguard_name), \
                    self.assertRaises(RequestHumanTakeover):
                protected_fleet_anchors(config)

    def test_protected_fleet_rejects_actual_anchor_mismatch(self):
        config = SimpleNamespace(
            OpsiTraining_ProtectedMainShip='英仙座',
            OpsiTraining_ProtectedVanguardShip='伊吹',
        )
        ships = {1: candidate('企业'), 4: candidate('伊吹', position='vanguard')}
        with self.assertRaises(RequestHumanTakeover):
            validate_protected_fleet(ships, config)

    def test_only_rotation_slots_can_be_opened(self):
        inspector = TrainingFleetManager.__new__(TrainingFleetManager)
        inspector._is_selector = lambda: True
        inspector._fourth_row_y = lambda: self.fail('anchor must be rejected before UI lookup')
        for slot in (1, 4, 0, 7):
            with self.subTest(slot=slot), self.assertRaises(RequestHumanTakeover):
                inspector._open_slot(slot)

    def test_all_four_rotation_slots_are_editable(self):
        inspector = TrainingFleetManager.__new__(TrainingFleetManager)
        inspector._is_selector = lambda: True
        inspector._fourth_row_y = lambda: 300
        inspector._wait = lambda *args, **kwargs: None
        inspector.dock_favourite_set = lambda *args, **kwargs: None
        inspector.dock_sort_method_dsc_set = lambda *args, **kwargs: None
        inspector.dock_filter_set = lambda *args, **kwargs: None
        inspector.device = SimpleNamespace(click=lambda button: None)
        with patch('module.os.training.DOCK_SCROLL.set_top') as set_top:
            for slot in (2, 3, 5, 6):
                with self.subTest(slot=slot):
                    inspector._open_slot(slot)
        self.assertEqual(set_top.call_count, 4)

    def test_unknown_and_empty_name_ocr_are_rejected_without_identity_guess(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        inspector.appear = lambda *args, **kwargs: True
        inspector.device.screenshot = lambda: None
        for raw_name in ('', '未知舰船'):
            with self.subTest(raw_name=raw_name), patch('module.os.training_ui.Ocr') as ocr:
                ocr.return_value.ocr.return_value = raw_name
                with patch('module.os.training_ui.cv2.imread', return_value=np.ones((2, 2, 3), dtype=np.uint8)):
                    with self.assertRaises(RequestHumanTakeover):
                        inspector.read_ship()

    def test_unknown_catalog_faction_must_be_rejected(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        inspector.appear = lambda *args, **kwargs: True
        inspector.device.screenshot = lambda: None
        fake_data = {'rarity': 3, 'faction': 95, 'type': 1, 'max_stars': 5, 'group': 99999}
        with patch.dict('module.os.training_ui.CATALOG', {'测试舰': fake_data}, clear=False), \
                patch('module.os.training_ui.Ocr') as ocr, \
                patch('module.os.training_ui.Digit') as digit, \
                patch('module.os.training_ui.cv2.imread', return_value=np.ones((2, 2, 3), dtype=np.uint8)), \
                patch('module.os.training_ui.cv2.matchTemplate', return_value=np.zeros((1, 1), dtype=np.float32)):
            ocr.return_value.ocr.return_value = ['测试舰', '测试舰']
            digit.return_value.ocr.return_value = 90
            with self.assertRaises(RequestHumanTakeover):
                inspector.read_ship()

    def test_level_120_does_not_request_array_awakening(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        ship = candidate('120级船', level=120, cap=120)
        inspector.awaken_once = lambda **kwargs: self.fail('level 120 must not awaken')
        self.assertIs(inspector.awaken_for_training(ship), ship)

    def test_no_candidate_retains_current_without_fleet_edit(self):
        current = {
            1: candidate('英仙座'), 2: candidate('当前主力'),
            3: candidate('当前主力2', level=125, cap=125),
            4: candidate('伊吹', position='vanguard'),
            5: candidate('当前先锋', position='vanguard'),
            6: candidate('当前先锋2', position='vanguard'),
        }
        requirement = TrainingRequirement(frozenset({'皇家'}), 'main', 1, '皇家主力技术测试I')

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                                              cross_set=lambda **kwargs: None)
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.edits = 0

            def _check_cn(self):
                return None

            def ui_ensure(self, page):
                return None

            def inspect_map_fleet(self, opsi):
                return current

            def _available_ships(self, opsi, requirement=None):
                return set()

            def find_candidates(self, *args, **kwargs):
                return []

            def _deploy(self, opsi, before, planned):
                self.edits += sum(before[slot].name != planned[slot].name for slot in (2, 3, 5, 6))

        opsi = SimpleNamespace(
            os_init=lambda **kwargs: None,
            globe_goto=lambda *args: None,
            name_to_zone=lambda name: name,
        )
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', requirement)
            manager = Manager()
            manager.maintain(opsi)
        self.assertEqual(manager.edits, 0)

    def test_maintenance_searches_rainbows_even_with_four_trainable_currents(self):
        current = {1: candidate('英仙座'), 2: candidate('主力甲'), 3: candidate('主力乙'),
                   4: candidate('伊吹', position='vanguard'),
                   5: candidate('先锋甲', position='vanguard'),
                   6: candidate('先锋乙', position='vanguard')}
        rainbow = {
            'main': ShipCandidate('彩主力', '皇家', 'main', 90, True, False),
            'vanguard': ShipCandidate('彩先锋', '重樱', 'vanguard', 90, True, False),
        }

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                                              cross_set=lambda **kwargs: None)
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.planned = None

            def _check_cn(self):
                pass

            def ui_ensure(self, page):
                pass

            def inspect_map_fleet(self, opsi):
                return current

            def _available_ships(self, opsi):
                return {ship.name for ship in rainbow.values()}

            def find_candidates(self, side, factions, excluded, **kwargs):
                return [rainbow[side]] if kwargs.get('rarity') == 'ultra' else []

            def _deploy(self, opsi, before, planned):
                self.planned = planned

        opsi = SimpleNamespace(os_init=lambda **kwargs: None,
                               globe_goto=lambda *args: None,
                               name_to_zone=lambda name: name)
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', None)
            manager = Manager()
            manager.maintain(opsi)
        self.assertIn('彩主力', {manager.planned[2].name, manager.planned[3].name})
        self.assertIn('彩先锋', {manager.planned[5].name, manager.planned[6].name})

    def test_catalog_type_and_faction_match_source_game_data(self):
        source_path = EVIDENCE / 'game-data' / 'ship_data_statistics.json'
        if not source_path.exists():
            self.skipTest('game-data fixture is not present')
        source = json.loads(source_path.read_text(encoding='utf-8'))
        samples = ('企业', '柴郡', '英仙座', '伊吹', '泛用型布里', '涅普顿', '江风·META')
        for name in samples:
            with self.subTest(name=name):
                data = CATALOG[name]
                records = [item for key, item in source.items() if key.startswith(str(data['group']))]
                self.assertTrue(records)
                self.assertEqual(data['type'], records[0]['type'])
                self.assertEqual(data['faction'], records[0]['nationality'])

        for faction, filter_name in FILTER_FACTIONS.items():
            self.assertTrue(filter_name)
            self.assertIn(faction, FACTIONS.values())

    def test_optional_verified_ui_fixtures_are_cn_rgb_images(self):
        fixture_names = ('current-ship.png', 'current-slot3.png', 'current-slot5.png', 'current-slot6.png')
        present = [EVIDENCE / name for name in fixture_names if (EVIDENCE / name).exists()]
        if not present:
            self.skipTest('training UI fixtures are not present')
        for path in present:
            with self.subTest(path=path.name):
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                self.assertIsNotNone(image)
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                self.assertEqual((image.shape[1], image.shape[0]), (1280, 720))
                self.assertEqual(image.shape[2], 3)

    def test_catalog_name_rejects_unknown_but_accepts_verified_aliases(self):
        self.assertIsNone(catalog_name(''))
        self.assertIsNone(catalog_name('完全未知'))
        self.assertEqual(catalog_name('朝咀'), '朝凪')
        self.assertEqual(catalog_name('八舞耶俱矢八舞夕弦'), '八舞耶俱矢·八舞夕弦')

    def test_verified_level_120_stored_three_million_snapshot(self):
        fixtures = (
            ('current-slot5.png', ['朝咀', '朝咀'], '朝凪'),
            ('current-slot6.png', ['八舞耶俱矢八舞夕弦', '八舞耶俱矢八舞夕弦'],
             '八舞耶俱矢·八舞夕弦'),
        )
        for filename, raw_names, expected_name in fixtures:
            path = EVIDENCE / filename
            if not path.exists():
                self.skipTest(f'{filename} is not present')
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            self.assertIsNotNone(image)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            inspector = TrainingShipInspector.__new__(TrainingShipInspector)
            inspector.config = SimpleNamespace(SERVER='cn')
            inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
            inspector.appear = lambda *args, **kwargs: True

            # Keep the actual fixture image, star template matching, level OCR,
            # and stored-XP OCR.  Only the known dual-ROI name OCR is stabilized
            # because the bundled OCR model is not deterministic on these CN
            # screenshots in every environment.
            real_ocr = training_ui.Ocr

            def ocr_factory(buttons, **kwargs):
                if kwargs.get('name') == 'TrainingName':
                    return SimpleNamespace(ocr=lambda current_image: raw_names)
                return real_ocr(buttons, **kwargs)

            with self.subTest(filename=filename), patch(
                    'module.os.training_ui.Ocr', side_effect=ocr_factory):
                ship = inspector.read_ship()
            self.assertEqual(ship.name, expected_name)
            self.assertEqual(ship.level, 120)
            self.assertEqual(ship.stored_exp, 3_000_000)
            self.assertEqual(ship.level_cap, 120)
            self.assertTrue(ship.fully_limit_broken)

    def test_scrolled_card_geometry_failure_is_safe(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = lambda *args, **kwargs: None
        inspector.dock_favourite_set = lambda *args, **kwargs: None
        inspector.dock_sort_method_dsc_set = lambda *args, **kwargs: None
        inspector.dock_filter_set = lambda *args, **kwargs: None
        inspector.device = SimpleNamespace(
            screenshot=lambda: None,
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
        )
        with patch('module.os.training_ui.DOCK_SCROLL.set_top'), \
                patch('module.os.training_ui.dock_cards', return_value=[]):
            with self.assertRaises(RequestHumanTakeover):
                inspector.find_candidates('main', frozenset(), set())


if __name__ == '__main__':
    unittest.main()
