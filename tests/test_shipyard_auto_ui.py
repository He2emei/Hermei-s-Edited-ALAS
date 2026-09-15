import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import RequestHumanTakeover
from module.shipyard.auto import AutoShipyard
from module.shipyard.auto_policy import server_day
from module.shipyard.auto_ui import panel_cost, panel_coins, required_level
from module.shipyard.leveling import ShipyardLeveler, book_counts, level_gain


ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/shipyard_auto'


class ShipyardAutoGuardTest(unittest.TestCase):
    def harness(self):
        obj = AutoShipyard.__new__(AutoShipyard)
        obj._day = server_day(datetime.now())
        obj.device = SimpleNamespace(click_record_clear=Mock())
        obj._shipyard_buy_confirm = Mock()
        obj.auto_set_amount = lambda target: target
        return obj

    def test_wrong_price_or_over_daily_limit_never_confirms(self):
        for offsets, amount, reading in (((0,), 10, (10, 600, 9283)),
                                         ((9,), 2, (2, 1650, 9283))):
            obj = self.harness()
            obj.auto_observe = lambda: reading
            with self.assertRaises(RequestHumanTakeover):
                obj._confirm_purchase('PR', '柴郡', offsets, amount)
            obj._shipyard_buy_confirm.assert_not_called()

    def test_confirmation_requires_exact_deduction_and_quantity_reset(self):
        for after in ((1, 0, 6283), (0, 0, 9283)):
            obj = self.harness()
            obj.auto_observe = Mock(side_effect=[(10, 3000, 9283), after])
            with self.assertRaises(RequestHumanTakeover):
                obj._confirm_purchase('PR', '柴郡', (0,), 10)
            obj._shipyard_buy_confirm.assert_called_once()

    def test_server_day_change_never_confirms(self):
        obj = self.harness()
        obj._day = '2020-01-01'
        with self.assertRaises(RequestHumanTakeover):
            obj._confirm_purchase('PR', '柴郡', (0,), 10)
        obj._shipyard_buy_confirm.assert_not_called()

    def test_success_and_partial_recovery_counts(self):
        obj = self.harness()
        obj.auto_observe = Mock(side_effect=[(9, 6000, 6283), (0, 0, 283)])
        self.assertEqual(obj._confirm_purchase('DR', '吾妻', (0,), 9), (9,))

    def test_new_settings_are_generated_and_timestamps_are_read_only(self):
        args = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        settings = args['Shipyard']['ShipyardAuto']
        self.assertFalse(settings['Enable']['value'])
        for key in ('PrLastRun', 'DrLastRun'):
            self.assertEqual(settings[key]['display'], 'disabled')

    def scan_harness(self):
        obj = self.harness()
        old = datetime(2020, 1, 1)
        obj.config = SimpleNamespace(SERVER='cn', ShipyardAuto_PrLastRun=old, ShipyardAuto_DrLastRun=old,
            args={'Shipyard': {group: {'ResearchSeries': {'option': [1]}}
                              for group in ('Shipyard', 'ShipyardDr')}}, task_delay=Mock())
        obj.device.screenshot = Mock()
        obj.device.image = np.zeros((720, 1280, 3), dtype='uint8')
        obj.ui_ensure = Mock()
        obj._shipyard_set_series = Mock()
        obj.shipyard_bottom_navbar_ensure = lambda left: setattr(obj, 'slot', left)
        obj.auto_name = lambda: {1: '海王星', 2: '伊吹', 3: '吾妻'}.get(obj.slot, '吾妻')
        obj.appear = lambda *a, **kw: False
        return obj

    def test_full_ship_switches_to_next_name_and_rarity(self):
        obj = self.scan_harness()
        obj._candidate = Mock(side_effect=['full', 'done', 'done'])
        obj.run_auto()
        self.assertEqual([c[0][2:4] for c in obj._candidate.call_args_list],
                         [('海王星', 'PR'), ('伊吹', 'PR'), ('吾妻', 'DR')])
        obj.config.task_delay.assert_called_once_with(server_update=True)

    def test_insufficient_coins_blocks_more_ships_and_book_feeding(self):
        obj = self.scan_harness()
        obj._candidate = Mock(side_effect=['coins', 'coins'])
        obj.run_auto()
        self.assertEqual(obj._candidate.call_count, 2)
        self.assertTrue(all(c[0][-1] is False for c in obj._candidate.call_args_list))
        self.assertEqual(obj.config.ShipyardAuto_PrLastRun.year, 2020)
        self.assertEqual(obj.config.ShipyardAuto_DrLastRun.year, 2020)
        obj.config.task_delay.assert_called_once_with(minute=60)

    def test_every_ship_full_is_not_recorded_as_ten_purchases(self):
        obj = self.scan_harness()
        obj._candidate = Mock(return_value='full')
        obj.run_auto()
        self.assertEqual(obj.config.ShipyardAuto_PrLastRun.year, 2020)
        self.assertEqual(obj.config.ShipyardAuto_DrLastRun.year, 2020)
        obj.config.task_delay.assert_called_once_with(server_update=True)

    def test_unknown_identity_is_deferred_not_declared_full(self):
        obj = self.scan_harness()
        obj.auto_name = lambda: None
        obj._candidate = Mock()
        obj.run_auto()
        obj._candidate.assert_not_called()
        obj.config.task_delay.assert_called_once_with(minute=60)

    def test_book_selector_cap_requires_verified_level_100_preview(self):
        for gain, expected in ((99, 7), (98, None)):
            obj = ShipyardLeveler.__new__(ShipyardLeveler)
            obj.device = SimpleNamespace(image=None, click_record_clear=Mock())
            obj._book_click = Mock()
            with patch('module.shipyard.leveling.book_counts', side_effect=[(5, 0, 3000, 0), (7, 0, 3000, 0)]), \
                    patch('module.shipyard.leveling.level_gain', return_value=gain):
                if expected is None:
                    with self.assertRaises(RequestHumanTakeover):
                        obj._set_books(0, 15, base_level=1)
                else:
                    self.assertEqual(obj._set_books(0, 15, base_level=1), expected)


class ShipyardScreenshotTest(unittest.TestCase):
    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def test_cost_is_total_not_next_unit_price(self):
        for name, cost in (('shipyard-cheshire-coin1', 0), ('shipyard-cheshire-coin2', 0),
                           ('shipyard-cheshire-coin3', 150), ('shipyard-cheshire-coin9', 2400)):
            im = self.image(name)
            self.assertEqual(panel_cost(im), cost)
            self.assertEqual(panel_coins(im), 9283)

    def test_development_and_fate_level_gates(self):
        self.assertEqual(required_level(self.image('shipyard-series3')), 10)
        self.assertEqual(required_level(self.image('shipyard-odin-fate-ready'), True), 100)

    def test_fate_total_has_a_different_right_aligned_position(self):
        for amount in (1, 2, 5):
            im = self.image('shipyard-fate-preview' + str(amount))
            self.assertEqual(panel_cost(im, True), 1050 * amount)
            self.assertEqual(panel_coins(im, True), 89667)

    def test_thin_one_in_level_gain_and_actual_book_deduction(self):
        for name, gain, count, stock in (('shipyard-exp-dialog', 0, 0, 2722),
                                        ('shipyard-exp-preview1', 7, 1, 2722),
                                        ('shipyard-exp-preview2', 10, 2, 2722),
                                        ('shipyard-book-after-confirm', 0, 0, 2720)):
            im = self.image(name)
            self.assertEqual(level_gain(im), gain)
            self.assertEqual(book_counts(im), (count, 0, stock, 0))
