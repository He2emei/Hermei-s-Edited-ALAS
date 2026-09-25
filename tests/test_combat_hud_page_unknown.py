"""The live battle HUD that blocked the page poll of a restarted scheduler.

Live 2026-09-25 14:21:41, dump log/error/1790317301661 (profile alas2, task Commission): the guard
found the scheduler stopped and started it again while a battle of the event was running. The
page poll of the new process saw the battle HUD, which is not a page, printed `Unknown ui page`
for ten seconds and ended in `CRITICAL | Game page unknown`.

The archived frame is tests/fixtures/combat_hud_page_unknown/battle-hud-1421.png (verbatim copy
of the dump). The other two frames of that directory are the pause menu and its confirmation
dialog, built on the archived OS map frame of the same zone because the archived dump holds only
the one screenshot (Error.ScreenshotLength = 1).
"""
import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat import battle_result
from module.combat.assets import QUIT_RECONFIRM
from module.combat.battle_result import (COMBAT_HUD_MAX_ATTEMPT, COMBAT_HUD_PATIENCE,
                                         handle_combat_hud, match_combat_hud_button,
                                         match_combat_quit_button)
from module.combat_ui.assets import PAUSE_Star, QUIT
from module.ui.page import page_os
from module.ui.ui import UI

from tests.test_battle_result_skip import ClickContractDevice

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/combat_hud_page_unknown'

# The battle HUD frame of the dump, the pause menu, the confirmation dialog, and the OS map the
# sequence is expected to end on.
HUD = 'battle-hud-1421'
PAUSED = 'battle-paused-1421'
CONFIRM = 'battle-quit-confirm-1421'
MAP = 'os-map-cleared'

HUD_PAUSE_AREA = (1234, 36, 1250, 57)
QUIT_AREA = (420, 490, 593, 548)
RECONFIRM_AREA = (749, 501, 828, 540)


def image(name):
    if name == MAP:
        return np.asarray(Image.open(
            ROOT / 'tests/fixtures/battle_result' / 'os-map-cleared.png').convert('RGB'))
    return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))


def clear():
    battle_result.combat_hud_pause_timer.reset()
    battle_result.combat_hud_pause_timer._start = 0
    battle_result.combat_hud_quit_timer.reset()
    battle_result.combat_hud_quit_timer._start = 0
    battle_result.combat_hud_reconfirm_timer.reset()
    battle_result.combat_hud_reconfirm_timer._start = 0
    battle_result.combat_hud_attempt = 0
    battle_result.combat_hud_seen_at = 0.


class FakeApp:
    """Only the device is a stand-in; the handler runs as the real module code."""

    def __init__(self, frame):
        self.device = ClickContractDevice(frame)


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class PagePollApp:
    """The UI instance UI.ui_get_current_page() needs, with the real module code bound to it.

    The device serves the frames of a scripted sequence and moves to the next frame on every
    screenshot, so a poll that cannot leave a state fails the test instead of spinning.
    """

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
    get_interval_timer = ModuleBase.get_interval_timer
    interval_reset = ModuleBase.interval_reset
    interval_clear = ModuleBase.interval_clear
    match_template_color = ModuleBase.match_template_color
    image_crop = ModuleBase.image_crop
    loop = ModuleBase.loop
    ui_get_current_page = UI.ui_get_current_page
    ui_page_appear = UI.ui_page_appear

    def __init__(self, frames, hold=4, limit=400):
        self.frames = frames
        self.hold = hold
        self.limit = limit
        self.index = 0
        self.screenshots = 0
        self.interval_timer = {}
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Emulator_ControlMethod='MaaTouch', SERVER='cn',
                                      Emulator_ScreenshotMethod='nemu_ipc')
        self.device = ClickContractDevice(image(frames[0]))
        self.device.screenshot = self.screenshot
        self.device.has_cached_image = False
        self.device.app_is_running = lambda: True
        self.device.get_orientation = lambda: 1
        self.device.uninstall_minicap = lambda: None

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'page poll did not advance after {self.limit} screenshots')
        # Hold every frame for a few screenshots, then move on.
        if self.screenshots % self.hold == 0 and self.index + 1 < len(self.frames):
            self.index += 1
            self.device.image = image(self.frames[self.index])
        return self.device.image

    # The rest of the page poll is not the subject of this test.
    def ui_additional(self, get_ship=True):
        return False

    def handle_login_page(self, interval=3):
        return False


class CombatHudFrameTest(unittest.TestCase):
    """What the archived frame of the incident really holds."""

    def test_the_crash_frame_is_a_live_battle(self):
        frame = image(HUD)
        # The battle HUD of a combat that is running, recognized by the probe of
        # Combat.is_combat_executing().
        self.assertIs(match_combat_hud_button(frame), PAUSE_Star)
        # No page matched in the page poll, and the pause menu is not open yet.
        for page in (page_os,):
            self.assertFalse(page.check_button.match_template_color(frame, offset=(30, 30)))
        self.assertIsNone(match_combat_quit_button(frame))
        self.assertFalse(QUIT_RECONFIRM.match_luma(frame, offset=(20, 20)))

    def test_a_map_frame_is_not_a_battle(self):
        frame = image(MAP)
        self.assertIsNone(match_combat_hud_button(frame))
        self.assertIsNone(match_combat_quit_button(frame))


class CombatHudHandlerTest(unittest.TestCase):
    """The sequence that leaves the battle, and its bounds."""

    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_battle_hud_is_paused(self):
        app = FakeApp(image(HUD))
        self.assertTrue(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], HUD_PAUSE_AREA)
        self.assertEqual(list(app.device.click_record), ['PAUSE_Star'])

    def test_the_pause_menu_is_quit(self):
        """The menu covers the pause button, so the menu has to be recognized first."""
        app = FakeApp(image(PAUSED))
        self.assertIsNone(match_combat_hud_button(app.device.image))
        self.assertTrue(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], QUIT_AREA)
        self.assertEqual(list(app.device.click_record), ['QUIT'])

    def test_the_confirmation_dialog_is_confirmed(self):
        app = FakeApp(image(CONFIRM))
        self.assertTrue(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], RECONFIRM_AREA)
        self.assertEqual(list(app.device.click_record), ['QUIT_RECONFIRM'])

    def test_the_whole_sequence_ends_on_the_map(self):
        app = FakeApp(image(HUD))
        with patch.object(battle_result, 'monotonic', side_effect=[1., 1., 2., 3., 4., 5., 6.]):
            app.device.image = image(HUD)
            self.assertTrue(handle_combat_hud(app))
            app.device.image = image(PAUSED)
            self.assertTrue(handle_combat_hud(app))
            app.device.image = image(CONFIRM)
            self.assertTrue(handle_combat_hud(app))
        self.assertEqual(list(app.device.click_record), ['PAUSE_Star', 'QUIT', 'QUIT_RECONFIRM'])
        self.assert_in_area(app.device.clicked[0], HUD_PAUSE_AREA)
        self.assert_in_area(app.device.clicked[1], QUIT_AREA)
        self.assert_in_area(app.device.clicked[2], RECONFIRM_AREA)
        # The map is not a battle: the handler stops and the page poll can see page_os again.
        app.device.image = image(MAP)
        self.assertFalse(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 3)

    def test_the_click_interval_prevents_a_burst(self):
        app = FakeApp(image(HUD))
        with patch.object(battle_result, 'monotonic', return_value=1.):
            self.assertTrue(handle_combat_hud(app))
            self.assertFalse(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 1)

    def test_a_pause_menu_that_never_opens_stops_before_the_click_guard(self):
        """Six clicks at two seconds, then the page poll reports the page as it did before."""
        app = FakeApp(image(HUD))
        clicks = 0
        with patch.object(battle_result, 'monotonic', return_value=1.):
            for _ in range(30):
                battle_result.combat_hud_pause_timer.reset()
                battle_result.combat_hud_pause_timer._start = 0
                if handle_combat_hud(app):
                    clicks += 1
        self.assertEqual(clicks, COMBAT_HUD_MAX_ATTEMPT)
        self.assertLess(COMBAT_HUD_MAX_ATTEMPT, 12)

    def test_a_battle_that_never_ends_is_given_up(self):
        app = FakeApp(image(HUD))
        with patch.object(battle_result, 'monotonic', return_value=1.):
            self.assertTrue(handle_combat_hud(app))
        with patch.object(battle_result, 'monotonic', return_value=1. + COMBAT_HUD_PATIENCE + 1):
            self.assertFalse(handle_combat_hud(app))
        self.assertEqual(len(app.device.clicked), 1)


class PagePollTest(unittest.TestCase):
    """The page poll of a scheduler that was restarted while a battle was running."""

    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_the_poll_leaves_the_battle_instead_of_reporting_the_page(self):
        app = PagePollApp([HUD, HUD, HUD, PAUSED, PAUSED, CONFIRM, MAP], hold=3)
        page = app.ui_get_current_page()
        self.assertIs(page, page_os)
        self.assertEqual(list(app.device.click_record), ['PAUSE_Star', 'QUIT', 'QUIT_RECONFIRM'])
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_handler_the_poll_reports_the_page(self):
        """The pre-fix behaviour of the same frames, for the record.

        The poll only gives up once the ten second timer has both been accessed 20 times and run
        for ten seconds (Timer.reached()), so the stand-in device serves the same frame until the
        timer has really run out.
        """
        from module.exception import GamePageUnknownError
        app = PagePollApp([HUD], hold=1, limit=2000)
        with patch('module.ui.ui.handle_combat_hud', lambda app: False):
            with self.assertRaises(GamePageUnknownError):
                app.ui_get_current_page()
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
