"""Minimized native frame replay for ship pages seen after EXP settlement.

A recorded settlement loop latched an EXP state while a ship reveal was still
settling, then omitted GET_SHIP from its polling until the existing stuck timeout.
The generic 29x21 markers here come from two real CN terminal frames. Full original
screenshots remain local; account, resource, character and runtime data are not
part of the distributed fixtures.

The real Combat.combat_status and native ModuleBase matching replay an existing
battle-result and EXP_INFO_S fixture before presenting each unmodified marker on
a neutral 1280x720 canvas. The intermediate animation was not captured, so this
represents the observed EXP-latch state rather than a complete video sequence.
"""
import collections
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat.assets import GET_SHIP, NEW_SHIP
from module.combat.combat import Combat
from module.combat import new_ship_page
from module.device.control import Control

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/combat_get_ship_transition'
START = ROOT / 'tests/fixtures/auto_search_status/battle-result-1600.png'
EXP = ROOT / 'tests/fixtures/auto_search_exp_settlement/exp-settlement-0256.png'
MAP = ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'


def image(path):
    return np.asarray(Image.open(path).convert('RGB'))


class LoopLimitReached(Exception):
    """The real status loop did not reach the archived map within the bounded replay."""


class ReplayDevice:
    click = Control.click

    def __init__(self, frames, limit=40):
        self.frames = frames
        self.image = frames['start']
        self.limit = limit
        self.screenshots = 0
        self.clicks = []
        self.exit_on_get_ship = True
        self.history = []
        self.click_record = collections.deque(maxlen=20)
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB')

    @property
    def click_methods(self):
        return {'ADB': self.click_adb}

    def click_adb(self, x, y):
        self.clicks.append((x, y))
        name = self.history[-1]
        if name.startswith('BATTLE_STATUS_'):
            self.image = self.frames['exp']
        elif name.startswith('EXP_INFO_'):
            self.image = self.frames['ship']
        elif name == 'GET_SHIP' and self.image is self.frames['ship'] and self.exit_on_get_ship:
            self.image = self.frames['map']

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no map transition after {self.limit} screenshots')
        return self.image

    def sleep(self, *args, **kwargs):
        pass

    def screenshot_interval_set(self, *args, **kwargs):
        pass

    def handle_control_check(self, button):
        self.stuck_record_clear()
        name = str(button)
        self.click_record.append(name)
        self.history.append(name)

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def stuck_record_add(self, button):
        pass


class CombatStatusReplay:
    combat_status = Combat.combat_status
    loop = ModuleBase.loop
    ensure_button = ModuleBase.ensure_button
    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    match_template_color = ModuleBase.match_template_color
    get_interval_timer = ModuleBase.get_interval_timer
    interval_reset = ModuleBase.interval_reset
    handle_get_ship = Combat.handle_get_ship
    handle_get_items = Combat.handle_get_items
    handle_battle_status = Combat.handle_battle_status
    handle_exp_info = Combat.handle_exp_info
    is_combat_executing = Combat.is_combat_executing
    battle_status_click_interval = 0

    def __init__(self, ship_frame, limit=40):
        self.frames = {
            'start': image(START),
            'exp': image(EXP),
            'ship': ship_frame,
            'map': image(MAP),
        }
        self.device = ReplayDevice(self.frames, limit)
        self.interval_timer = {}
        self.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=30, GET_SHIP_TRIGGERED=False)

    def handle_story_skip(self, *args, **kwargs):
        return False

    def handle_popup_confirm(self, *args, **kwargs):
        return False

    def handle_urgent_commission(self, *args, **kwargs):
        return False

    def handle_guild_popup_cancel(self, *args, **kwargs):
        return False

    def handle_vote_popup(self, *args, **kwargs):
        return False

    def handle_mission_popup_ack(self, *args, **kwargs):
        return False

    def handle_auto_search_exit(self, *args, **kwargs):
        return False

    def handle_combat_mis_click(self, *args, **kwargs):
        return False

    def handle_in_stage(self):
        return False


class CombatGetShipTransitionTest(unittest.TestCase):
    def setUp(self):
        new_ship_page.confirm_click_timer.reset()
        new_ship_page.confirm_click_timer._start = 0
        new_ship_page.confirm_attempt = 0
        new_ship_page.confirm_clicked_at = 0.

    def tearDown(self):
        new_ship_page.confirm_click_timer.reset()
        new_ship_page.confirm_click_timer._start = 0
        new_ship_page.confirm_attempt = 0
        new_ship_page.confirm_clicked_at = 0.

    def ship_frame(self, name):
        marker = image(EVIDENCE / name)
        self.assertEqual(marker.shape, (21, 29, 3))
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Retain only the exact original GET_SHIP marker; full production frames
        # remain local. This is the minimal page cue driving the native handler.
        frame[610:631, 1082:1111] = marker
        return frame

    def test_real_ship_introduction_frames_match_the_native_get_ship_asset(self):
        for name in ('get-ship-blue-marker.png', 'get-ship-purple-marker.png'):
            with self.subTest(name=name):
                app = CombatStatusReplay(self.ship_frame(name))
                app.device.image = app.frames['ship']
                self.assertTrue(app.appear(GET_SHIP, offset=(20, 20)))
                self.assertFalse(NEW_SHIP.appear_on(self.ship_frame(name)))
                self.assertFalse(app.config.GET_SHIP_TRIGGERED)

    def test_the_real_get_ship_handler_clicks_and_leaves_both_frames(self):
        button_area = (1000, 631, 1055, 689)
        for name in ('get-ship-blue-marker.png', 'get-ship-purple-marker.png'):
            with self.subTest(name=name):
                app = CombatStatusReplay(self.ship_frame(name))
                app.device.image = app.frames['ship']
                self.assertTrue(app.handle_get_ship())
                self.assertEqual(app.device.history, ['GET_SHIP'])
                self.assertEqual(len(app.device.clicks), 1)
                x, y = app.device.clicks[0]
                self.assertTrue(button_area[0] <= x <= button_area[2])
                self.assertTrue(button_area[1] <= y <= button_area[3])
                self.assertIs(app.device.image, app.frames['map'])
                self.assertFalse(app.config.GET_SHIP_TRIGGERED)

    def test_combat_status_leaves_the_real_ship_page_for_the_map(self):
        """The exact post-EXP ship page must be handled by the real status loop."""
        for name in ('get-ship-blue-marker.png', 'get-ship-purple-marker.png'):
            with self.subTest(name=name):
                app = CombatStatusReplay(self.ship_frame(name))
                app.combat_status(expected_end=lambda: app.device.image is app.frames['map'])
                self.assertIs(app.device.image, app.frames['map'])
                self.assertIn('EXP_INFO_S', app.device.history)
                self.assertLess(app.device.screenshots, app.device.limit)


    def test_real_non_ship_screens_do_not_match_or_click_the_ship_handler(self):
        other = ROOT / 'tests/fixtures/new_ship_page'
        for path in (START, EXP, MAP, other / 'new-ship-0304.png', other / 'other-confirm-0727.png'):
            with self.subTest(path=path.name):
                app = CombatStatusReplay(image(path))
                app.device.image = app.frames['ship']
                self.assertFalse(app.appear(GET_SHIP, offset=(20, 20)))
                self.assertFalse(app.handle_get_ship())
                self.assertEqual(app.device.clicks, [])
                self.assertFalse(app.config.GET_SHIP_TRIGGERED)

    def test_the_normal_exp_screen_still_exits_without_a_ship_click(self):
        app = CombatStatusReplay(image(MAP))
        app.frames['ship'] = app.frames['map']
        app.combat_status(expected_end=lambda: app.device.image is app.frames['map'])
        self.assertIn('EXP_INFO_S', app.device.history)
        self.assertNotIn('GET_SHIP', app.device.history)

    def test_an_unknown_post_exp_page_is_left_for_the_existing_timeout(self):
        app = CombatStatusReplay(np.zeros((720, 1280, 3), dtype=np.uint8), limit=20)
        with self.assertRaises(LoopLimitReached):
            app.combat_status(expected_end=lambda: app.device.image is app.frames['map'])
        self.assertIn('EXP_INFO_S', app.device.history)
        self.assertNotIn('GET_SHIP', app.device.history)

    def test_the_existing_one_second_ship_click_interval_is_preserved(self):
        app = CombatStatusReplay(self.ship_frame('get-ship-blue-marker.png'))
        app.device.image = app.frames['ship']
        app.device.exit_on_get_ship = False
        self.assertTrue(app.handle_get_ship())
        self.assertFalse(app.handle_get_ship())
        self.assertEqual(app.device.history, ['GET_SHIP'])


if __name__ == '__main__':
    unittest.main()
