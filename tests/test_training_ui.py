import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import RequestHumanTakeover, ScriptError
from module.os import training_ui
from module.os.training_policy import ShipCandidate, TrainingRequirement
from module.os.training_ui import (
    CATALOG,
    FACTIONS,
    FILTER_FACTIONS,
    TrainingShipInspector,
    TrainingAwakeningDeferred,
    catalog_name,
    detail_ship_lock,
    dock_card_lock,
    protected_fleet_anchors,
    validate_protected_fleet,
)
from module.os.training import TrainingFleetManager
from module.os_handler.assets import ORDER_ENTER
from module.os_handler.port import PORT_CHECK
from module.retire.assets import DOCK_EMPTY


ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT.parent / 'code_workflow' / 'evidence' / '2026-09-08'


def candidate(name, faction='白鹰', position='main', level=90, cap=None):
    return ShipCandidate(name, faction, position, level, False, True, None, cap)


class TrainingUiReviewTest(unittest.TestCase):
    def test_cn_york_shared_name_cannot_select_royal_identity(self):
        self.assertIsNone(catalog_name("约克"))
        self.assertIsNone(catalog_name("_约克"))
        self.assertEqual(catalog_name("约克城"), "约克城")

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

    def test_priority_availability_uses_locked_faction_lane_filter_without_editing_slot(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager._open_selector = Mock()
        manager._open_slot = Mock()
        manager._scan_selection = Mock(side_effect=[{'普通主力'}, {'普通先锋'}, object()])
        manager._cancel_slot = Mock()
        manager._close_selector = Mock()

        available = manager._available_ships(SimpleNamespace(), ('虎',))

        self.assertEqual(available, {'普通主力', '普通先锋', '虎'})
        self.assertEqual([call[0][0] for call in manager._open_slot.call_args_list], [2, 5, 5])
        target_call = manager._open_slot.call_args_list[-1]
        self.assertEqual(target_call[0][1].name, '虎')
        self.assertEqual(target_call[0][1].position, 'vanguard')
        self.assertTrue(target_call[1]['priority'])
        self.assertEqual(manager._cancel_slot.call_count, 3)
        manager._close_selector.assert_called_once()

    def test_priority_deployment_slot_uses_exact_position_faction_and_ur_filters(self):
        inspector = TrainingFleetManager.__new__(TrainingFleetManager)
        inspector._is_selector = lambda: True
        inspector._fourth_row_y = lambda: 300
        inspector._wait = lambda *args, **kwargs: None
        inspector.dock_favourite_set = Mock()
        inspector.dock_sort_method_dsc_set = Mock()
        inspector.dock_filter_set = Mock()
        inspector.device = SimpleNamespace(click=Mock())
        target = ShipCandidate('虎', '皇家', 'vanguard', 71, True, False, None, 120, True)
        with patch('module.os.training.DOCK_SCROLL.set_top'):
            inspector._open_slot(5, target, priority=True)
        inspector.dock_filter_set.assert_called_once_with(
            index='vanguard', faction='royal', rarity='ultra')

    def test_available_scan_continues_on_small_measured_scroll_progress(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(screenshot=Mock(), sleep=Mock(), click_record_clear=Mock(),
                                         image=np.zeros((720, 1280, 3), dtype=np.uint8))
        card = SimpleNamespace(area=(100, 100, 238, 304))

        readings = iter(('企业', '柴郡', '独角兽', '独角兽'))

        def visible_names():
            name = next(readings)
            manager._visible_cards = [card]
            manager._raw_names = [name]
            return [name]

        manager._visible_names = visible_names
        scroll_positions = iter((0.20, 0.24, 0.28, 1.0))
        with patch('module.os.training.DOCK_SCROLL.cal_position',
                   side_effect=lambda **kwargs: next(scroll_positions)), \
                patch('module.os.training.DOCK_SCROLL.next_page') as next_page:
            names = manager._scan_selection()

        self.assertEqual(names, {'企业', '柴郡', '独角兽'})
        self.assertEqual(next_page.call_count, 3)
        # Each 0.04 thumb advance is below the old drag_threshold exit, but is
        # measured progress and therefore safely resets the click history.
        self.assertEqual(manager.device.click_record_clear.call_count, 3)

    def test_priority_availability_rejects_unlocked_copy_and_double_checks_locked_card(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        button = SimpleNamespace(area=(100, 100, 238, 304))
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                         screenshot=Mock(), sleep=Mock())
        manager._visible_names = lambda: (
            setattr(manager, '_visible_cards', [button]) or
            setattr(manager, '_raw_names', ['虎']) or ['虎'])

        with patch('module.os.training.DOCK_SCROLL.cal_position', return_value=1.0), \
                patch('module.os.training.dock_cards', return_value=[button]), \
                patch('module.os.training.dock_card_lock', return_value=False):
            self.assertIsNone(manager._scan_selection('虎', fail_if_missing=False))

        manager.device.screenshot.reset_mock()
        with patch('module.os.training.DOCK_SCROLL.cal_position', return_value=1.0), \
                patch('module.os.training.dock_cards', return_value=[button]), \
                patch('module.os.training.dock_card_lock', side_effect=[True, True]):
            self.assertIs(manager._scan_selection('虎', fail_if_missing=False), button)
        self.assertEqual(manager.device.screenshot.call_count, 2)

    def test_deployment_return_exits_ny_port_before_map_verification(self):
        state = ['port']
        exits = []
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(screenshot=lambda: None, sleep=lambda _: None)
        manager.appear = lambda asset, **kwargs: (
            asset is PORT_CHECK and state[0] == 'port'
            or asset is ORDER_ENTER and state[0] == 'map')

        def port_quit(**kwargs):
            exits.append(kwargs)
            state[0] = 'map'

        opsi = SimpleNamespace(
            os_init=lambda **kwargs: None,
            globe_goto=lambda zone: None,
            name_to_zone=lambda zone: zone,
            # The port transition fooled this weaker map check in the live run.
            is_in_map=lambda: True,
            port_quit=port_quit,
        )
        manager._return_to_ny_map_after_deploy(opsi)
        self.assertEqual(exits, [{'skip_first_screenshot': True}])

    def test_deployment_return_exits_port_before_os_init(self):
        state = ["port"]
        order = []
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(screenshot=lambda: None, sleep=lambda _: None)
        manager.appear = lambda asset, **kwargs: (
            asset is PORT_CHECK and state[0] == "port"
            or asset is ORDER_ENTER and state[0] == "map")

        def port_quit(**kwargs):
            order.append("port_quit")
            state[0] = "map"

        def os_init(**kwargs):
            order.append("os_init")
            if state[0] == "port":
                raise ScriptError("zone_init looped from NY port")

        opsi = SimpleNamespace(
            os_init=os_init,
            globe_goto=lambda zone: order.append("globe_goto"),
            name_to_zone=lambda zone: zone,
            is_in_map=lambda: state[0] == "map",
            port_quit=port_quit,
        )
        manager._return_to_ny_map_after_deploy(opsi)
        self.assertEqual(order, ["port_quit", "os_init", "globe_goto"])

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

    def test_only_authorized_priority_120_uses_array_for_final_awakening(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(PriorityTraining_Ships='虎',
                                           PriorityTraining_Allow125Awakening=True)
        ship = candidate('虎', level=120, cap=120)
        calls = []
        inspector.awaken_once = lambda **kwargs: calls.append(kwargs['use_array']) or 'success'
        inspector.read_ship = lambda: candidate('虎', level=125, cap=125)
        result = inspector.awaken_for_training(ship, ('虎',))
        self.assertEqual(calls, [True])
        self.assertEqual(result.level, 125)

    def test_unrelated_120_target_never_uses_array(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(PriorityTraining_Ships='虎',
                                           PriorityTraining_Allow125Awakening=True)
        ship = candidate('普通', level=120, cap=120)
        calls = []
        inspector.awaken_once = lambda **kwargs: calls.append(kwargs['use_array']) or 'success'
        inspector.read_ship = lambda: candidate('普通', level=125, cap=125)
        inspector.awaken_for_training(ship, ('虎',))
        self.assertEqual(calls, [])

    def test_insufficient_awakening_resources_are_a_typed_deferral(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(PriorityTraining_Ships='虎',
                                           PriorityTraining_Allow125Awakening=True)
        ship = candidate('虎', level=100, cap=100)
        inspector.awaken_once = lambda **kwargs: 'insufficient'
        with self.assertRaises(TrainingAwakeningDeferred):
            inspector.awaken_for_training(ship, ('虎',))

    def test_non_resource_awakening_results_still_take_over(self):
        for result in ('no_exp', 'unexpected_array', 'timeout', 'unknown'):
            inspector = TrainingShipInspector.__new__(TrainingShipInspector)
            inspector.config = SimpleNamespace(PriorityTraining_Ships='虎',
                                               PriorityTraining_Allow125Awakening=True)
            inspector.awaken_once = lambda **kwargs: result
            with self.subTest(result=result), self.assertRaises(RequestHumanTakeover):
                inspector.awaken_for_training(candidate('虎', level=100, cap=100), ('虎',))

    def test_awakening_without_level_or_cap_progress_takes_over(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(PriorityTraining_Ships='虎',
                                           PriorityTraining_Allow125Awakening=True)
        ship = candidate('虎', level=100, cap=100)
        inspector.awaken_once = lambda **kwargs: 'success'
        inspector.read_ship = lambda: ship
        with self.assertRaises(RequestHumanTakeover):
            inspector.awaken_for_training(ship, ('虎',))

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

            def _available_ships(self, opsi, priority_names=()):
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

            def _available_ships(self, opsi, priority_names=()):
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

    def test_maintenance_searches_priority_target_with_full_trainable_fleet(self):
        current = {1: candidate('英仙座'), 2: candidate('主力甲'), 3: candidate('主力乙'),
                   4: candidate('伊吹', position='vanguard'),
                   5: candidate('先锋甲', position='vanguard'),
                   6: candidate('先锋乙', position='vanguard')}
        target = ShipCandidate('虎', '皇家', 'vanguard', 119, True, False, 0, 120, True)

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                                              PriorityTraining_Ships='虎',
                                              PriorityTraining_Allow125Awakening=True,
                                              cross_set=lambda **kwargs: None)
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.planned = None
                self.target_search = False

            def _check_cn(self): pass
            def ui_ensure(self, page): pass
            def inspect_map_fleet(self, opsi): return current
            def _available_ships(self, opsi, priority_names=()):
                self.available_targets = tuple(priority_names)
                return {'虎'}
            def find_candidates(self, side, factions, excluded, **kwargs):
                if kwargs.get('target_names') == {'虎'}:
                    self.target_search = True
                    self.search_args = (side, factions, kwargs.get('rarity'), kwargs.get('available'))
                    return [target]
                return []
            def _deploy(self, opsi, before, planned): self.planned = planned

        opsi = SimpleNamespace(os_init=lambda **kwargs: None,
                               globe_goto=lambda *args: None,
                               name_to_zone=lambda name: name)
        with patch('module.os.training.CATALOG', {'虎': {'type': 2, 'faction': 2, 'rarity': 6}}), \
                patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', None)
            manager = Manager()
            manager.maintain(opsi)
        self.assertTrue(manager.target_search)
        self.assertEqual(manager.available_targets, ('虎',))
        self.assertEqual(manager.search_args, ('vanguard', frozenset(), None, {'虎'}))
        self.assertIn('虎', {manager.planned[5].name, manager.planned[6].name})

    def test_deployed_locked_priority_target_in_full_rainbow_fleet_does_not_force_dock_search(self):
        current = {
            1: candidate('英仙座'),
            2: ShipCandidate('彩主力', '皇家', 'main', 90, True, False, None, 100, True),
            3: ShipCandidate('另一彩主力', '皇家', 'main', 90, True, False, None, 100, True),
            4: candidate('伊吹', position='vanguard'),
            5: ShipCandidate('虎', '皇家', 'vanguard', 90, True, False, None, 120, True),
            6: ShipCandidate('另一彩先锋', '皇家', 'vanguard', 90, True, False, None, 120, True),
        }

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                                              PriorityTraining_Ships='虎',
                                              PriorityTraining_Allow125Awakening=True,
                                              cross_set=lambda **kwargs: None)
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.deploy_calls = 0

            def _check_cn(self): pass
            def ui_ensure(self, page): pass
            def inspect_map_fleet(self, opsi): return current
            def _available_ships(self, opsi, priority_names=()):
                self.fail('deployed locked target must not force a dock scan')
            def find_candidates(self, *args, **kwargs):
                self.fail('all four rainbow slots and explicit targets are already satisfied')
            def _deploy(self, opsi, before, planned): self.deploy_calls += 1
            def fail(self, message): raise AssertionError(message)

        opsi = SimpleNamespace(os_init=lambda **kwargs: None,
                               globe_goto=lambda *args: None,
                               name_to_zone=lambda name: name)
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', None)
            manager = Manager()
            manager.maintain(opsi)
        self.assertEqual(manager.deploy_calls, 1)

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

    def test_live_regensburg_stored_exp_uses_verified_max_suffix_fallback(self):
        path = ROOT / 'tests/fixtures/opsi_training_regensburg_1166908_max.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
        inspector.appear = lambda *args, **kwargs: True
        real_ocr = training_ui.Ocr

        def ocr_factory(buttons, **kwargs):
            if kwargs.get('name') == 'TrainingName':
                return SimpleNamespace(ocr=lambda current_image: ['雷根斯堡', '雷根斯堡'])
            return real_ocr(buttons, **kwargs)

        with patch('module.os.training_ui.Ocr', side_effect=ocr_factory):
            ship = inspector.read_ship()
        self.assertEqual(ship.name, '雷根斯堡')
        self.assertEqual(ship.level, 120)
        self.assertEqual(ship.stored_exp, 1_166_908)
        self.assertEqual(ship.level_cap, 120)

    def test_stored_exp_fallback_rejects_unknown_suffix_and_over_cap_value(self):
        path = ROOT / 'tests/fixtures/opsi_training_regensburg_1166908_max.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        for tail, value in (('/M?X', 1_166_908), ('/M8X', 3_000_001)):
            inspector = TrainingShipInspector.__new__(TrainingShipInspector)
            inspector.config = SimpleNamespace(SERVER='cn')
            inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
            inspector.appear = lambda *args, **kwargs: True

            def ocr_factory(buttons, **kwargs):
                if kwargs.get('name') == 'TrainingName':
                    text = ['雷根斯堡', '雷根斯堡']
                elif kwargs.get('name') == 'TrainingStoredExp':
                    text = '1I166908/M8X'
                elif kwargs.get('name') == 'TrainingStoredExpTail':
                    text = tail
                else:
                    return training_ui.Ocr(buttons, **kwargs)
                return SimpleNamespace(ocr=lambda current_image: text)

            with self.subTest(tail=tail, value=value), \
                    patch('module.os.training_ui.Ocr', side_effect=ocr_factory), \
                    patch('module.os.training_ui.Digit') as digit, \
                    self.assertRaises(RequestHumanTakeover):
                digit.return_value.ocr.return_value = value
                inspector.read_ship()

    def test_live_z23_retrofit_detail_is_identifiable(self):
        path = ROOT / 'tests/fixtures/opsi_z23_retrofit_detail.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
        inspector.appear = lambda *args, **kwargs: True
        ship = inspector.read_ship()
        self.assertEqual(ship.name, 'Z23.改')
        self.assertEqual(ship.faction, '铁血')
        self.assertEqual(ship.position, 'vanguard')
        self.assertEqual(ship.level, 120)
        self.assertTrue(ship.fully_limit_broken)
        self.assertEqual(ship.stored_exp, 331_039)
        self.assertEqual(ship.level_cap, 120)

    def test_live_white_dragon_detail_is_identifiable(self):
        path = ROOT / 'tests/fixtures/opsi_white_dragon_detail.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
        inspector.appear = lambda *args, **kwargs: True
        ship = inspector.read_ship()
        self.assertEqual(ship.name, '白龙')
        self.assertEqual(ship.faction, '重樱')
        self.assertEqual(ship.position, 'main')
        self.assertEqual(ship.level, 118)
        self.assertTrue(ship.is_rainbow)
        self.assertEqual(ship.level_cap, 120)
        self.assertIsNone(ship.stored_exp)

    def test_live_albacore_mu_detail_keeps_variant_identity(self):
        path = ROOT / 'tests/fixtures/dorm_albacore_mu_detail_20260929.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
        inspector.appear = lambda *args, **kwargs: True
        ship = inspector.read_ship()
        self.assertEqual(ship.name, '大青花鱼(μ兵装)')
        self.assertNotEqual(ship.name, catalog_name('大青花鱼'))
        self.assertIsNone(catalog_name('未知舰船(u兵装)'))
        self.assertEqual((ship.faction, ship.position, ship.level), ('白鹰', 'submarine', 120))
        self.assertTrue(ship.is_locked)
        self.assertTrue(ship.fully_limit_broken)
        self.assertEqual((ship.stored_exp, ship.level_cap), (0, 120))

    def test_live_incomplete_stars_remain_incomplete(self):
        path = ROOT / 'tests/fixtures/opsi_locked_musashi_alas2_20260925.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
        inspector.appear = lambda *args, **kwargs: True
        ship = inspector.read_ship()
        # The legacy fixture filename says Musashi, but the actual title is Azuma.
        self.assertEqual(ship.name, '吾妻')
        self.assertTrue(ship.is_locked)
        self.assertFalse(ship.fully_limit_broken)

    def test_live_locked_and_unlocked_detail_labels(self):
        for filename, expected in (
                ('opsi_locked_musashi_alas2_20260925.png', True),
                ('opsi_unlocked_bulin_alas2_20260925.png', False)):
            image = cv2.cvtColor(cv2.imread(str(ROOT / 'tests/fixtures' / filename)), cv2.COLOR_BGR2RGB)
            with self.subTest(filename=filename):
                self.assertIs(detail_ship_lock(image), expected)

    def test_live_dock_card_lock_separates_material_from_locked_ship(self):
        from module.base.button import Button
        image = cv2.cvtColor(cv2.imread(str(ROOT / 'tests/fixtures/opsi_lock_dock_alas2_20260925.png')),
                             cv2.COLOR_BGR2RGB)
        def card(col):
            x = round(93 + col * (164 + 2 / 3))
            return Button((x, 529, x + 138, 733), (0, 0, 0), (x, 529, x + 138, 733))
        self.assertIs(dock_card_lock(image, card(5)), True)
        self.assertIs(dock_card_lock(image, card(3)), False)

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
        inspector.appear = lambda *args, **kwargs: False
        with patch('module.os.training_ui.DOCK_SCROLL.set_top'), \
                patch('module.os.training_ui.dock_cards', return_value=[]):
            with self.assertRaises(RequestHumanTakeover):
                inspector.find_candidates('main', frozenset(), set())

    def test_empty_rarity_faction_filter_has_no_candidates(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = lambda *args, **kwargs: None
        inspector.dock_favourite_set = lambda *args, **kwargs: None
        inspector.dock_sort_method_dsc_set = lambda *args, **kwargs: None
        inspector.dock_filter_set = lambda *args, **kwargs: None
        inspector.device = SimpleNamespace(screenshot=lambda: None)
        inspector.appear = lambda asset, **kwargs: asset is DOCK_EMPTY
        with patch('module.os.training_ui.DOCK_SCROLL.set_top') as set_top:
            self.assertEqual(inspector.find_candidates('vanguard', frozenset({'铁血'}),
                                                       set(), rarity='ultra'), [])
        set_top.assert_not_called()

    def test_priority_candidate_scan_uses_exact_catalog_filter_and_selects_target(self):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = Mock()
        inspector.dock_favourite_set = Mock()
        inspector.dock_sort_method_dsc_set = Mock()
        inspector.dock_filter_set = Mock()
        inspector.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            screenshot=Mock(), sleep=Mock(), click=Mock(), click_record_clear=Mock())
        inspector.appear = lambda *args, **kwargs: False
        inspector.ship_info_enter = Mock()
        inspector.read_ship = lambda: ShipCandidate('虎', '皇家', 'vanguard', 71, True,
                                                    False, 0, 120, True)
        inspector.wait_until_appear = Mock()
        button = SimpleNamespace(area=(100, 100, 238, 304))
        scroll = SimpleNamespace(set_top=Mock(), cal_position=Mock(return_value=1.0),
                                 edge_threshold=0.01, drag_threshold=0.1, next_page=Mock())
        with patch('module.os.training_ui.CATALOG',
                   {'虎': {'type': 2, 'faction': 2, 'rarity': 6}}), \
                patch('module.os.training_ui.dock_cards', return_value=[button]), \
                patch('module.os.training_ui.LevelOcr') as level_ocr, \
                patch('module.os.training_ui.Ocr') as name_ocr, \
                patch('module.os.training_ui.dock_card_lock', return_value=True):
            level_ocr.return_value.ocr.return_value = [71]
            name_ocr.return_value.ocr.return_value = ['虎']
            with patch.object(inspector, 'click_record_clear', create=True):
                result = inspector.find_candidates(
                    'vanguard', frozenset(), set(), needed=1, available={'虎'},
                    target_names={'虎'}, scroll=scroll)

        self.assertEqual([ship.name for ship in result], ['虎'])
        inspector.dock_filter_set.assert_called_once_with(
            sort='level', index='vanguard', faction=['royal'], rarity='ultra')
        inspector.ship_info_enter.assert_called_once_with(button, long_click=False)

    def test_paid_deployment_cancellation_never_reports_success_or_inspects_fleet(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.config = SimpleNamespace(PriorityTraining_Ships='')
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                         click=Mock(), sleep=Mock(), screenshot=Mock())
        manager._open_selector = Mock()
        manager._fourth_row_y = Mock(return_value=300)
        manager._open_slot = Mock()
        manager._scan_selection = Mock(return_value=object())
        manager._one_ship_selected = Mock(return_value=True)
        manager._cancel_slot = Mock()
        manager._wait = Mock()
        manager._is_selector = Mock(return_value=True)
        manager._label = Mock(return_value='立刻前往')
        manager.handle_popup_cancel = Mock(return_value=True)
        manager._close_selector = Mock()
        manager.inspect_map_fleet = Mock(side_effect=AssertionError('paid deploy must not be verified as success'))
        current = {slot: candidate('old' + str(slot), position='main' if slot < 4 else 'vanguard')
                   for slot in range(1, 7)}
        planned = dict(current)
        planned[2] = candidate('new', position='main')
        opsi = SimpleNamespace()

        with patch('module.os.training.crop', return_value=np.zeros((48, 50, 3), dtype=np.uint8)), \
                patch('module.os.training.read_deployment_cost', return_value=3):
            result = manager._deploy(opsi, current, planned)

        self.assertFalse(result)
        manager.handle_popup_cancel.assert_called_once_with('OPSI_TRAINING_DEPLOY_PAID')
        manager.inspect_map_fleet.assert_not_called()


class TrainingAwakeningDeferredRecoveryTest(unittest.TestCase):
    def make_manager(self, os_init_side_effect=None, globe_goto_side_effect=None):
        writes = []
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.config = SimpleNamespace(
            SERVER='cn', OpsiFleet_Fleet=4,
            cross_set=lambda **kwargs: writes.append(kwargs))
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        manager._check_cn = Mock()
        manager.ui_ensure = Mock()
        manager.inspect_map_fleet = Mock()
        manager.find_candidates = Mock(side_effect=AssertionError('unexpected candidate search'))
        manager._awaken_planned_ship = Mock(side_effect=[
            candidate('主力1', level=100, cap=105),
            TrainingAwakeningDeferred('no resources'),
        ])
        manager._deploy = Mock(side_effect=AssertionError('must discard the pending deployment plan'))
        current = {
            1: ShipCandidate('英仙座', '白鹰', 'main', 125, True, True, None, 125, True),
            2: ShipCandidate('目标舰', '白鹰', 'main', 100, True, True, 0, 100, True),
            3: ShipCandidate('主力2', '白鹰', 'main', 100, True, True, 0, 100, True),
            4: ShipCandidate('伊吹', '重樱', 'vanguard', 125, True, True, None, 125, True),
            5: ShipCandidate('先锋1', '重樱', 'vanguard', 90, True, True, None, 120, True),
            6: ShipCandidate('先锋2', '重樱', 'vanguard', 90, True, True, None, 120, True),
        }
        manager.inspect_map_fleet.return_value = current
        plan = SimpleNamespace(success=True, slots=dict(current), reason='')
        opsi = SimpleNamespace(
            os_init=Mock(side_effect=os_init_side_effect),
            globe_goto=Mock(side_effect=globe_goto_side_effect),
            name_to_zone=Mock(return_value='NY'))
        shipyard_patch = patch('module.shipyard.development.ShipyardDevelopment')
        priority_patch = patch('module.os.training.priority_ship_names', return_value=())
        planning_patch = patch('module.os.training.plan_rotation', side_effect=[plan, plan])
        time_patch = patch('module.os.training.time.time', return_value=4567)
        shipyard = shipyard_patch.start()
        priority_patch.start()
        planning_patch.start()
        time_patch.start()
        self.addCleanup(time_patch.stop)
        self.addCleanup(planning_patch.stop)
        self.addCleanup(priority_patch.stop)
        self.addCleanup(shipyard_patch.stop)
        shipyard.return_value.inspect_current_project.return_value = ('test ship', None)
        return manager, opsi, writes

    def test_maintain_discards_plan_after_prior_awakening_succeeds(self):
        manager, opsi, writes = self.make_manager()
        self.assertFalse(manager.maintain(opsi))
        self.assertEqual(manager._awaken_planned_ship.call_count, 2)
        manager._deploy.assert_not_called()
        self.assertEqual(opsi.globe_goto.call_count, 2)
        opsi.globe_goto.assert_called_with('NY')
        self.assertEqual(writes, [{
            'keys': 'OpsiHazard1Leveling.OpsiTraining.LastCheck', 'value': 4567,
        }])

    def test_maintain_recovery_os_init_failure_leaves_last_check_unchanged(self):
        manager, opsi, writes = self.make_manager(
            os_init_side_effect=[None, ScriptError('map recovery failed')])
        with self.assertRaisesRegex(ScriptError, 'map recovery failed'):
            manager.maintain(opsi)
        self.assertEqual(manager._awaken_planned_ship.call_count, 2)
        manager._deploy.assert_not_called()
        opsi.globe_goto.assert_called_once_with('NY')
        self.assertEqual(writes, [])

    def test_maintain_recovery_globe_failure_leaves_last_check_unchanged(self):
        manager, opsi, writes = self.make_manager(
            globe_goto_side_effect=[None, ScriptError('NY recovery failed')])
        with self.assertRaisesRegex(ScriptError, 'NY recovery failed'):
            manager.maintain(opsi)
        self.assertEqual(manager._awaken_planned_ship.call_count, 2)
        manager._deploy.assert_not_called()
        self.assertEqual(opsi.globe_goto.call_count, 2)
        self.assertEqual(writes, [])

    def test_resource_shortage_recovers_to_ny_then_records_retry(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        writes = []
        manager.config = SimpleNamespace(cross_set=lambda **kwargs: writes.append(kwargs))
        opsi = SimpleNamespace(os_init=Mock(), globe_goto=Mock(), name_to_zone=Mock(return_value='NY'))
        with patch('module.os.training.time.time', return_value=4567):
            self.assertFalse(manager._defer_after_awakening_resource_shortage(opsi))
        opsi.os_init.assert_called_once_with(skip_first_auto_search=True)
        opsi.name_to_zone.assert_called_once_with('NY')
        opsi.globe_goto.assert_called_once_with('NY')
        self.assertEqual(writes, [{
            'keys': 'OpsiHazard1Leveling.OpsiTraining.LastCheck', 'value': 4567,
        }])

    def test_failed_map_recovery_does_not_record_retry(self):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        writes = []
        manager.config = SimpleNamespace(cross_set=lambda **kwargs: writes.append(kwargs))
        opsi = SimpleNamespace(os_init=Mock(side_effect=ScriptError('map recovery failed')),
                               globe_goto=Mock(), name_to_zone=Mock(return_value='NY'))
        with patch('module.os.training.time.time', return_value=4567):
            with self.assertRaisesRegex(ScriptError, 'map recovery failed'):
                manager._defer_after_awakening_resource_shortage(opsi)
        opsi.globe_goto.assert_not_called()
        self.assertEqual(writes, [])


class TrainingUnavailableProjectRecoveryTest(unittest.TestCase):
    def make_manager(self):
        writes = []

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(
                    SERVER='cn', OpsiFleet_Fleet=4,
                    cross_set=lambda **kwargs: writes.append(kwargs))
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))

            def _check_cn(self):
                return None

            def ui_ensure(self, page):
                return None

            def inspect_map_fleet(self, opsi):
                self.fail('unavailable project must preserve the deployed fleet')

            def find_candidates(self, *args, **kwargs):
                self.fail('unavailable project must not search candidates')

            def _awaken_planned_ship(self, *args, **kwargs):
                self.fail('unavailable project must not awaken ships')

            def _deploy(self, *args, **kwargs):
                self.fail('unavailable project must not deploy ships')

            def fail(self, message):
                raise AssertionError(message)

        return Manager(), writes

    def test_unavailable_working_project_recovers_map_and_schedules_retry(self):
        from module.shipyard.development import WorkingProjectUnavailable

        manager, writes = self.make_manager()
        opsi = SimpleNamespace(os_init=Mock(), globe_goto=Mock())
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard, \
                patch('module.os.training.time.time', return_value=1234):
            shipyard.return_value.inspect_current_project.side_effect = WorkingProjectUnavailable(
                'No visible working ship found in shipyard series')
            self.assertFalse(manager.maintain(opsi))
        opsi.os_init.assert_called_once_with(skip_first_auto_search=True)
        opsi.globe_goto.assert_not_called()
        self.assertEqual(writes, [{
            'keys': 'OpsiHazard1Leveling.OpsiTraining.LastCheck', 'value': 1234,
        }])

    def test_other_script_errors_still_propagate_without_retry_timestamp(self):
        manager, writes = self.make_manager()
        opsi = SimpleNamespace(os_init=Mock())
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.side_effect = ScriptError('unknown page')
            with self.assertRaisesRegex(ScriptError, 'unknown page'):
                manager.maintain(opsi)
        opsi.os_init.assert_not_called()
        self.assertEqual(writes, [])

    def test_map_recovery_error_propagates_without_retry_timestamp(self):
        from module.shipyard.development import WorkingProjectUnavailable

        manager, writes = self.make_manager()
        opsi = SimpleNamespace(os_init=Mock(side_effect=ScriptError('map recovery failed')))
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard, \
                patch('module.os.training.time.time', return_value=1234):
            shipyard.return_value.inspect_current_project.side_effect = WorkingProjectUnavailable(
                'No visible working ship found in shipyard series')
            with self.assertRaisesRegex(ScriptError, 'map recovery failed'):
                manager.maintain(opsi)
        opsi.os_init.assert_called_once_with(skip_first_auto_search=True)
        self.assertEqual(writes, [])


if __name__ == '__main__':
    unittest.main()
