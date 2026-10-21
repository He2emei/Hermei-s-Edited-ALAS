import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat.combat import BATTLE_PREPARATION
from module.exception import RequestHumanTakeover
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.os_ash import ash as ash_module
from module.os_ash.ash import AshCombat


ROOT = Path(__file__).parents[1]
CONFIRM_FRAME = np.asarray(Image.open(
    ROOT / 'tests/fixtures/meta_confirm/prepare-confirm-20261021.png'
).convert('RGB'))


class FakeClock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        self.now += 0.5
        return self.now


class FixtureDevice:
    def __init__(self, image):
        self.image = image
        self.clicked = []
        self.click_record = collections.deque(maxlen=20)

    def stuck_record_add(self, button):
        pass

    def click(self, button):
        self.clicked.append(button)


def make_combat(server='cn', image=CONFIRM_FRAME):
    combat = AshCombat.__new__(AshCombat)
    combat.device = FixtureDevice(image)
    combat.config = SimpleNamespace(SERVER=server, BUTTON_OFFSET=30)
    combat.interval_timer = {}
    combat.handle_get_items = lambda: False
    return combat


class MetaFleetConfirmationTest(unittest.TestCase):
    def setUp(self):
        for button in (POPUP_CANCEL, POPUP_CONFIRM, BATTLE_PREPARATION):
            button.clear_offset()

    def assert_real_popup_buttons_match(self, combat):
        self.assertTrue(combat.appear(POPUP_CANCEL, offset=(20, 20)))
        self.assertTrue(combat.appear(POPUP_CONFIRM, offset=(20, 20)))

    def test_real_fixture_and_handler_confirm_only_exact_cn_prompt(self):
        combat = make_combat()
        self.assert_real_popup_buttons_match(combat)
        self.assertTrue(combat.handle_battle_preparation())
        self.assertEqual(combat.device.clicked, [POPUP_CONFIRM])

    def test_unknown_or_consumption_prompt_never_confirms(self):
        for prompt in ('是否消耗石油并出击？', '保存当前舰队并出击？', '保存当前编队并出击'):
            with self.subTest(prompt=prompt):
                combat = make_combat()
                self.assert_real_popup_buttons_match(combat)
                with patch.object(ash_module.Ocr, 'ocr', return_value=prompt):
                    self.assertFalse(combat.handle_battle_preparation())
                self.assertEqual(combat.device.clicked, [])

    def test_non_cn_client_does_not_ocr_or_confirm(self):
        combat = make_combat(server='en')
        with patch.object(ash_module.Ocr, 'ocr', side_effect=AssertionError('OCR must not run')):
            self.assertFalse(combat.handle_battle_preparation())
        self.assertEqual(combat.device.clicked, [])

    def test_persistent_confirm_waits_between_clicks_then_takes_over(self):
        combat = make_combat()
        clock = FakeClock()
        with patch.object(ash_module.Ocr, 'ocr', return_value='保存当前编队并出击？'), \
                patch('module.base.timer.time', clock):
            self.assertTrue(combat.handle_battle_preparation())
            self.assertEqual(len(combat.device.clicked), 1)
            self.assertTrue(combat.handle_battle_preparation())
            self.assertEqual(len(combat.device.clicked), 1)
            for _ in range(10):
                self.assertTrue(combat.handle_battle_preparation())
                if len(combat.device.clicked) == 2:
                    break
            self.assertEqual(len(combat.device.clicked), 2)
            for _ in range(10):
                self.assertTrue(combat.handle_battle_preparation())
                if len(combat.device.clicked) == 3:
                    break
            self.assertEqual(len(combat.device.clicked), 3)
            takeover = False
            for _ in range(10):
                try:
                    combat.handle_battle_preparation()
                except RequestHumanTakeover as error:
                    self.assertIn('META fleet confirmation', str(error))
                    takeover = True
                    break
            self.assertTrue(takeover)
        self.assertEqual(combat.device.clicked, [POPUP_CONFIRM] * 3)

    def test_generic_preparation_and_beacon_completion_paths_are_preserved(self):
        combat = make_combat(image=np.zeros_like(CONFIRM_FRAME))
        combat.appear_then_click = lambda button, **kwargs: button is BATTLE_PREPARATION
        self.assertTrue(combat.handle_battle_preparation())

        combat = make_combat(image=np.zeros_like(CONFIRM_FRAME))
        combat.appear_then_click = lambda *args, **kwargs: False
        combat.appear = lambda button, **kwargs: button is ash_module.BEACON_REWARD
        with self.assertRaises(ash_module.AshBeaconFinished):
            combat.handle_battle_preparation()


if __name__ == '__main__':
    unittest.main()
