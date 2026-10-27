import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from unittest.mock import Mock

from module.freebies.assets import BUY_CONFIRM, FREE_SUPPLY_PACK
from module.freebies.supply_pack import (SupplyPack, SUPPLY_PACK_PREVIEW_CANCEL,
                                         SUPPLY_PACK_PREVIEW_NAME, SUPPLY_PACK_CONFIRM_CANCEL,
                                         SUPPLY_PACK_CONFIRM_BLUE)
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.ui.assets import SUPPLY_PACK_CHECK
from module.ui.page import page_supply_pack


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'supply_pack'


def frame_with_tab(fragment_name):
    fragment = np.asarray(Image.open(FIXTURES / fragment_name).convert('RGB'))
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[294:350, 0:181] = fragment
    return frame


def preview_frame(fragment_name):
    panel = np.asarray(Image.open(FIXTURES / fragment_name).convert('RGB'))
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    if 'confirm' in fragment_name:
        frame[163:558, 338:942] = panel
    else:
        frame[167:638, 245:1035] = panel
    return frame


class SupplyPackEntryRegressionTest(unittest.TestCase):
    def test_cn_offer_packs_tab_matches_real_selected_frame(self):
        frame = frame_with_tab('alas2-offer-packs-tab-current-tab.png')
        self.assertTrue(SUPPLY_PACK_CHECK.match_template_color(frame, offset=(0, 0), similarity=0.85,
                                                               threshold=30))
        self.assertEqual(SUPPLY_PACK_CHECK.button, (0, 294, 181, 350))

    def test_old_selected_recommendation_tab_does_not_match_supply_pack(self):
        frame = frame_with_tab('alas2-weekly-current-tab.png')
        self.assertFalse(SUPPLY_PACK_CHECK.match_template_color(frame, offset=(0, 0), similarity=0.85,
                                                                threshold=30))

    def test_existing_free_pack_asset_is_preserved(self):
        FREE_SUPPLY_PACK.ensure_template()
        self.assertEqual(FREE_SUPPLY_PACK.area, (264, 615, 312, 641))
        self.assertEqual(FREE_SUPPLY_PACK.image.shape[:2], (26, 48))

    def test_horizontal_scan_is_bounded_and_clears_history_only_on_progress(self):
        manager = SupplyPack.__new__(SupplyPack)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        swipes = []
        clears = []

        class Device:
            def swipe_vector(self, vector, **kwargs):
                swipes.append(vector)
                if len(swipes) <= 2:
                    image[200:650, 220:980] = len(swipes) * 20

            def sleep(self, _seconds):
                pass

            def screenshot(self):
                manager.device.image = image

            def click_record_clear(self):
                clears.append(True)

        manager.device = Device()
        manager.device.image = image
        manager.appear = lambda button, **_kwargs: button is page_supply_pack.check_button
        manager.match_template_color = lambda button, **_kwargs: button is page_supply_pack.check_button
        self.assertFalse(manager._scan_weekly_free_price(max_swipes=8))
        self.assertEqual(len(swipes), 3)
        self.assertEqual(len(clears), 2)

    def test_stable_free_price_marker_opens_preview_once(self):
        manager = SupplyPack.__new__(SupplyPack)
        manager.device = Mock()
        manager.appear = lambda button, **_kwargs: True
        manager.match_template_color = lambda button, **_kwargs: button is page_supply_pack.check_button
        self.assertTrue(manager._scan_weekly_free_price())
        manager.device.click.assert_called_once_with(FREE_SUPPLY_PACK)
        manager.device.swipe_vector.assert_not_called()

    def test_real_paid_preview_reads_400_and_is_rejected(self):
        manager = SupplyPack.__new__(SupplyPack)
        manager.device = SimpleNamespace(image=preview_frame('weekly-paid-preview-panel.png'),
                                         screenshot=Mock())
        manager.appear = Mock(return_value=True)
        name, free = manager._preview_evidence()
        self.assertTrue(name)
        self.assertFalse(free)
        self.assertTrue(SUPPLY_PACK_PREVIEW_CANCEL.match_template_color(
            manager.device.image, offset=(10, 10), similarity=0.85, threshold=30))

    def test_generic_real_zero_preview_reads_strict_zero(self):
        manager = SupplyPack.__new__(SupplyPack)
        manager.device = SimpleNamespace(image=preview_frame('generic-zero-preview-panel.png'),
                                         screenshot=Mock())
        manager.appear = Mock(return_value=True)
        name, free = manager._preview_evidence()
        self.assertTrue(name)
        self.assertTrue(free)

    def test_generic_confirmation_buttons_match_real_zero_confirm_frame(self):
        frame = preview_frame('generic-zero-confirm-panel.png')
        self.assertTrue(SUPPLY_PACK_CONFIRM_CANCEL.match_template_color(
            frame, offset=(10, 10), similarity=0.85, threshold=30))
        self.assertTrue(SUPPLY_PACK_CONFIRM_BLUE.match_template_color(
            frame, offset=(10, 10), similarity=0.85, threshold=30))

    def test_empty_or_mismatched_price_never_passes_preview_gate(self):
        manager = SupplyPack.__new__(SupplyPack)
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), screenshot=Mock())
        manager.appear = Mock(return_value=True)
        readings = iter(['test pack', '', '', 'test pack', '', ''])
        manager._ocr_text = lambda *_args, **_kwargs: next(readings)
        self.assertIsNone(manager._preview_evidence())

    def test_confirmation_requires_exact_zero_and_same_name(self):
        manager = SupplyPack.__new__(SupplyPack)
        decision = manager._confirmation_decision
        self.assertTrue(decision('是否使用购买', '0钻石周礼包', '周礼包'))
        self.assertFalse(decision('是否使用购买', '400钻石周礼包', '周礼包'))
        self.assertFalse(decision('是否使用购买', '0钻石别的礼包', '周礼包'))
        self.assertIsNone(decision('', '', '周礼包'))

    def test_unknown_confirmation_cancels_known_popup_without_retry(self):
        manager = SupplyPack.__new__(SupplyPack)
        manager._scan_weekly_free_price = Mock(return_value=True)
        manager._preview_evidence = Mock(return_value=('周礼包', True))
        manager._collect_verified_purchase = Mock(return_value=False)
        manager._read_confirmation = Mock(return_value=None)
        manager._confirm_controls = Mock(return_value=True)
        manager._preview_controls = Mock(return_value=True)
        manager._wait_for = lambda predicate, **_kwargs: predicate()
        manager._cancel_pack_preview = Mock(return_value=True)
        manager.device = Mock()
        manager.appear = lambda button, **_kwargs: button not in (GET_ITEMS_1, GET_ITEMS_2)
        self.assertFalse(manager._buy_cn_weekly_free())
        manager.device.click.assert_any_call(BUY_CONFIRM)
        manager.device.click.assert_any_call(SUPPLY_PACK_CONFIRM_CANCEL)
        self.assertEqual(manager.device.click.call_count, 2)


if __name__ == '__main__':
    unittest.main()
