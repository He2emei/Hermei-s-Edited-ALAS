import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from module.freebies import event_supply
from module.freebies.event_supply import (EventSupply, canonical_event_name, event_window, exact_zero,
                                          has_convoy_base_name, is_zero_event_prompt, valid_listing,
                                          claim_label_matches)


FIXTURES = Path(__file__).parent / 'fixtures' / 'event_supply'


def read_rgb(path):
    return np.asarray(Image.open(path).convert('RGB'))


class TestEventSupplyEvidence(unittest.TestCase):
    def test_runtime_button_templates_have_content_and_reject_blank_frame(self):
        import numpy as np
        blank = np.zeros((720, 1280, 3), dtype=np.uint8)
        for button in (event_supply.EVENT_ENTRY_ICON, event_supply.EVENT_HOME,
                       event_supply.EVENT_PREVIEW_CANCEL, event_supply.EVENT_CONFIRM_CANCEL,
                       event_supply.EVENT_CONFIRM_BLUE):
            with self.subTest(button=button.name):
                button.ensure_template()
                self.assertGreater(float(button.image.std()), 1.0)
                self.assertFalse(button.match(blank, offset=(5, 5)))

    def test_current_event_date_window_is_closed_at_both_edges(self):
        self.assertFalse(event_window(datetime(2026, 10, 21)))
        self.assertTrue(event_window(datetime(2026, 10, 22)))
        self.assertTrue(event_window(datetime(2026, 11, 4, 23, 59)))
        self.assertFalse(event_window(datetime(2026, 11, 5)))
        self.assertFalse(event_window(datetime(2027, 10, 23)))

    def test_price_requires_literal_zero(self):
        for text in ('', ' ', 'O', '0钻石', '6', '¥0'):
            with self.subTest(text=text):
                self.assertFalse(exact_zero(text))
        self.assertTrue(exact_zero('0'))
        self.assertTrue(exact_zero(' 0 '))

    def test_supported_roman_suffixes_are_preserved_without_guessing_tier(self):
        for suffix in ('III', 'V', 'VI', 'VII', 'Ⅲ', 'Ⅵ', 'Ⅶ', 'lll'):
            with self.subTest(suffix=suffix):
                name = event_supply.EVENT_NAME_PREFIX + suffix
                self.assertIsNotNone(canonical_event_name(name))
                self.assertTrue(has_convoy_base_name(name))
        for name in ('船团建设礼包III', '船团宝藏回馈', '船团宝藏回馈VIII', ''):
            with self.subTest(name=name):
                self.assertIsNone(canonical_event_name(name))

    def test_zero_dialog_requires_both_exact_white_and_green_fragments(self):
        self.assertTrue(is_zero_event_prompt('是否使用购买', '0钻石船团宝藏回馈l川'))
        self.assertFalse(is_zero_event_prompt('是否使用购买', '6钻石船团宝藏回馈III'))
        self.assertFalse(is_zero_event_prompt('是否使用购买', '0钻石船团建设礼包III'))
        self.assertFalse(is_zero_event_prompt('', '0钻石船团宝藏回馈III'))

    def test_only_two_frame_exact_free_claimable_card_is_accepted(self):
        good = (event_supply.EVENT_NAME_PREFIX + 'lll', '可购买次数:1/1', True) * 2
        self.assertTrue(valid_listing(*good))
        for index, bad in ((0, '船团建设礼包III'), (1, '可购买次数:0/1'), (2, False),
                           (3, ''), (4, ''), (5, False)):
            args = list(good)
            args[index] = bad
            with self.subTest(index=index, bad=bad):
                self.assertFalse(valid_listing(*args))

    def test_zero_confirm_requires_two_good_frames_and_blank_second_price_is_cancelled(self):
        app = EventSupply.__new__(EventSupply)
        app.device = Mock()
        app.device.image = read_rgb(FIXTURES / 'confirm-evidence.png')
        blank = Image.fromarray(app.device.image.copy())
        draw = ImageDraw.Draw(blank)
        draw.rectangle((548, 330, 612, 365), fill=(100, 110, 118))
        draw.rectangle((660, 330, 839, 365), fill=(100, 110, 118))
        frames = [app.device.image, np.asarray(blank)]
        app.device.screenshot.side_effect = lambda: setattr(app.device, 'image', frames.pop(1))
        app.target_name = '船团宝藏回馈III'
        app.appear = Mock(return_value=True)
        self.assertFalse(app._zero_confirmation())
        app.device.click.assert_not_called()

    def test_known_dialog_with_paid_or_blank_price_is_cancelable_but_never_confirmed(self):
        app = EventSupply.__new__(EventSupply)
        app.device = Mock()
        app.target_name = event_supply.EVENT_NAME_PREFIX + 'III'
        white = Mock(ocr=Mock(return_value='是否使用购买'))
        green = Mock(ocr=Mock(return_value='6钻石船团建设礼包III'))
        app.appear = Mock(return_value=True)
        with patch.object(event_supply, 'Ocr', side_effect=[white, green]):
            self.assertFalse(app._zero_confirmation())
        app.device.click.assert_not_called()

    def test_real_claim_button_label_fixture_distinguishes_paid_label(self):
        free = read_rgb(FIXTURES / 'EVENT_CLAIM_LABEL.png')
        paid = read_rgb(FIXTURES / 'EVENT_PAID_LABEL.png')
        self.assertTrue(claim_label_matches(free))
        self.assertFalse(claim_label_matches(paid))

    def test_real_frame_ocr_and_template_evidence(self):
        app = EventSupply.__new__(EventSupply)
        app.device = Mock()
        app.device.image = read_rgb(FIXTURES / 'listing-evidence.png')
        card = app._card_evidence(321)
        self.assertEqual(card[0][:len(event_supply.EVENT_NAME_PREFIX)], event_supply.EVENT_NAME_PREFIX)
        self.assertTrue(canonical_event_name(card[0]))
        self.assertTrue(event_supply._available_count(card[1]))
        self.assertTrue(card[2])
        self.assertTrue(app._listing_header())
        self.assertEqual(app._find_claimable(), (421, card[0]))
        self.assertTrue(event_supply.EVENT_HOME.match(app.device.image, offset=0, similarity=0.90))

        app.device.image = read_rgb(FIXTURES / 'home-entry-evidence.png')
        self.assertTrue(event_supply.EVENT_ENTRY_ICON.match(app.device.image, offset=0, similarity=0.90))
        app.appear = Mock(return_value=True)
        self.assertTrue(app._entry())
        self.assertEqual(app.device.click.call_count, 1)

        app.device.image = read_rgb(FIXTURES / 'preview-evidence.png')
        app.target_name = card[0]
        self.assertTrue(app._preview_is_free())
        self.assertTrue(event_supply.EVENT_PREVIEW_CANCEL.match(app.device.image, offset=0, similarity=0.90))

        app.device.image = read_rgb(FIXTURES / 'confirm-evidence.png')
        app.appear = Mock(return_value=True)
        self.assertTrue(app._zero_confirmation())
        self.assertTrue(event_supply.EVENT_CONFIRM_CANCEL.match(app.device.image, offset=0, similarity=0.90))
        self.assertTrue(event_supply.EVENT_CONFIRM_BLUE.match(app.device.image, offset=0, similarity=0.90))

    def test_complete_flow_uses_zero_preview_then_zero_confirmation_then_get_items(self):
        app = EventSupply.__new__(EventSupply)
        app.config = Mock(SERVER='cn')
        app.device = Mock()
        app.device.image = read_rgb(FIXTURES / 'confirm-evidence.png')
        app.ui_ensure = Mock()
        app._is_home = Mock(return_value=True)
        app._entry = Mock(return_value=True)
        app._listing_header = Mock(return_value=True)
        app._find_claimable = Mock(side_effect=[(423, event_supply.EVENT_NAME_PREFIX + 'III')] + [None] * 7)
        app._preview_is_free = Mock(return_value=True)
        app._return_home = Mock(return_value=True)
        with patch.object(event_supply, 'event_window', return_value=True), \
                patch.object(app, 'appear', side_effect=[True, True, True, True, True]):
            self.assertTrue(app.run())
        clicked = [call[0][0] for call in app.device.click.call_args_list]
        self.assertEqual([button.name for button in clicked], [
            'EVENT_SUPPLY_REWARD_CARD', 'BUY_CONFIRM', 'EVENT_SUPPLY_CONFIRM_BLUE', 'GET_ITEMS_1'
        ])
        self.assertTrue(app._return_home.called)

    def test_paid_or_unknown_preview_never_reaches_confirmation(self):
        app = EventSupply.__new__(EventSupply)
        app.config = Mock(SERVER='cn')
        app.device = Mock()
        app.ui_ensure = Mock()
        app._is_home = Mock(return_value=True)
        app._entry = Mock(return_value=True)
        app._listing_header = Mock(return_value=True)
        app._find_claimable = Mock(return_value=(423, event_supply.EVENT_NAME_PREFIX + 'III'))
        app._preview_is_free = Mock(return_value=False)
        app._zero_confirmation = Mock()
        app._listing_header = Mock(return_value=True)
        app._return_home = Mock(return_value=True)
        app.appear = Mock(return_value=True)
        with patch.object(event_supply, 'event_window', return_value=True):
            self.assertFalse(app.run())
        app._zero_confirmation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
