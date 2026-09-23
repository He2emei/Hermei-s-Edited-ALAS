"""The battle result screen of an auto search battle that the status loop did not handle.

Live log/error/1790150413796 (2026-09-23 16:00:13, GemsFarming on campaign 2-4): the loop of
`AutoSearchCombat.auto_search_combat_status()` ended in `GameStuckError: Wait too long` after sixty
seconds without a single click.  The archived frame is the `VICTORY / 大获全胜 S / 战斗评价` result
screen, whose rank icon `BATTLE_STATUS_S` matches, but the handler of that screen,
`Combat.handle_battle_status()`, sat behind `_auto_search_status_confirm` — a flag that only a low
emotion popup of the moving phase arms.  `Waiting for {...}` of the dump is exactly the top part of
the loop and holds no `PAUSE`, no `BATTLE_STATUS_*` and no `EXP_INFO_*`, which is only possible when
the block behind that flag never ran.

These tests run the real loop of the class against the archived frame: the device serves the frame
and moves to the map once the result screen is clicked, and every handler except the result screen
handler is stubbed out, so the loop can only advance through the result screen.
"""
import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.base.utils import get_color
from module.combat.assets import BATTLE_STATUS_S
from module.combat.auto_search_combat import AutoSearchCombat
from module.combat.combat import Combat
from module.device.control import Control

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/auto_search_status'
# An operation siren map frame, the end condition of the loop once the result screen is gone.
MAP_FRAME = ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'

# Recognition signal of the result screen: the rank letter, measured (230.1, 239.0, 127.4) on the
# archived frame.  The button of the same asset is the clickable area of the screen.
RANK_AREA = (643, 297, 722, 317)
SKIP_AREA = (1000, 631, 1055, 689)


def image(path):
    return np.asarray(Image.open(path).convert('RGB'))


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class ResultScreenDevice:
    """A stand-in device that clicks through the real `Control.click()`.

    `Control.click()` takes a Button, not a coordinate, and registers the button in the click
    record, so the stand-in keeps that contract.  The frame is the archived result screen until a
    click arrives, then it is the map, where auto search keeps running.
    """

    click = Control.click

    def __init__(self, result_frame, map_frame, screenshot_limit=5000):
        self.frames = (result_frame, map_frame)
        self.image = result_frame
        self.screenshot_limit = screenshot_limit
        self.screenshots = 0
        self.clicked = []
        self.click_record = collections.deque(maxlen=20)
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB')

    @property
    def click_methods(self):
        return {'ADB': self.click_adb}

    def click_adb(self, x, y):
        self.clicked.append((x, y))
        # The game leaves the result screen for the map once the screen is clicked.
        self.image = self.frames[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.screenshot_limit:
            raise LoopLimitReached(f'no exit after {self.screenshot_limit} screenshots')
        return self.image

    def sleep(self, *args, **kwargs):
        pass

    def screenshot_interval_set(self, *args, **kwargs):
        pass

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record.append(str(button))

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        pass

    def stuck_record_add(self, button):
        pass


class StatusLoopApp:
    """The Alas instance `auto_search_combat_status()` needs, with the real loop bound to it.

    `_auto_search_status_confirm` is False, which is the state of the crash: the low emotion popup
    was handled during the moving phase, and the flag was cleared when the auto search option of the
    map was clicked, so the result screen had no handler at all.
    """

    auto_search_combat_status = AutoSearchCombat.auto_search_combat_status
    loop = ModuleBase.loop
    handle_get_ship = Combat.handle_get_ship
    handle_get_items = Combat.handle_get_items
    handle_battle_status = Combat.handle_battle_status
    handle_exp_info = Combat.handle_exp_info
    is_combat_executing = Combat.is_combat_executing
    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    match_template_color = ModuleBase.match_template_color
    ensure_button = ModuleBase.ensure_button
    battle_status_click_interval = 0
    _auto_search_status_confirm = False

    def __init__(self, result_frame, map_frame, screenshot_limit=5000):
        self.device = ResultScreenDevice(result_frame, map_frame, screenshot_limit)
        self.interval_timer = {}
        self.calls = collections.Counter()
        self.config = SimpleNamespace(SERVER='cn')

    def interval_reset(self, button, interval=3):
        pass

    def interval_clear(self, button, interval=3):
        pass

    def is_auto_search_running(self):
        self.calls['is_auto_search_running'] += 1
        # The click leaves the result screen for the map, where auto search keeps running.
        return self.device.image is self.device.frames[1]

    def handle_auto_search_map_option(self):
        self.calls['handle_auto_search_map_option'] += 1
        return False

    def __getattr__(self, item):
        if item in ('is_in_auto_search_menu', '_handle_auto_search_menu_missing',
                    'handle_popup_confirm',
                    'handle_urgent_commission', 'handle_story_skip', 'handle_guild_popup_cancel',
                    'handle_vote_popup', 'handle_mission_popup_ack'):
            def handler(*args, **kwargs):
                self.calls[item] += 1
                return False
            return handler
        raise AttributeError(item)


class AutoSearchStatusResultScreenTest(unittest.TestCase):
    """The loop of the crash has to skip the result screen instead of timing out."""

    def frame(self, name='battle-result-1600'):
        return image(EVIDENCE / (name + '.png'))

    def map_frame(self):
        return image(MAP_FRAME)

    def app(self, screenshot_limit=5000):
        return StatusLoopApp(self.frame(), self.map_frame(), screenshot_limit)

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_archived_frame_is_the_battle_result_screen(self):
        frame = self.frame()
        self.assertTrue(BATTLE_STATUS_S.appear_on(frame))
        self.assertEqual(tuple(BATTLE_STATUS_S.area), RANK_AREA)
        # The click target of the same asset is the clickable area of the result screen.
        self.assertEqual(tuple(BATTLE_STATUS_S.button), SKIP_AREA)
        color = get_color(frame, RANK_AREA)
        # Measured (230.1, 239.0, 127.4) on the archived frame: the yellow rank letter.
        self.assertGreater(color[0], 200)
        self.assertGreater(color[1], 200)
        self.assertLess(color[2], 160)

    def test_no_combat_is_executing_on_the_archived_frame(self):
        """`handle_battle_status()` returns early while a combat executes, so the frame of the
        crash must not look like a running combat.  The dump agrees: `PAUSE` is not in
        `Waiting for {...}`, so `is_combat_executing()` was never asked."""
        app = self.app()
        self.assertFalse(app.is_combat_executing())

    def test_the_status_loop_skips_the_result_screen_without_the_flag(self):
        app = self.app()
        self.assertFalse(app._auto_search_status_confirm)
        app.auto_search_combat_status()
        self.assertEqual(list(app.device.click_record), ['BATTLE_STATUS_S'])
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], SKIP_AREA)
        self.assertLess(app.device.screenshots, app.device.screenshot_limit)

    def test_without_the_handler_the_status_loop_never_ends(self):
        """The pre-fix behaviour of the same frame, for the record.

        Live 2026-09-23 16:00:13: the loop polled the frame for sixty seconds, clicked nothing and
        ended in `GameStuckError: Wait too long`.  Without the result screen handler the loop of the
        archived frame cannot advance, which the stand-in device reports as a screenshot limit.
        """
        app = self.app(screenshot_limit=50)
        with patch.object(StatusLoopApp, 'handle_battle_status', lambda self, *a, **kw: False):
            with self.assertRaises(LoopLimitReached):
                app.auto_search_combat_status()
        self.assertEqual(app.device.clicked, [])

    def test_the_result_screen_is_handled_before_the_auto_search_option(self):
        """Order of the loop: the result screen is a battle of the auto search that has ended, and
        the auto search option of the map is not on this screen, so the result screen is asked
        first and the loop cannot lose its click behind another handler."""
        order = []

        def battle_status(self, *args, **kwargs):
            order.append('battle_status')
            return Combat.handle_battle_status(self, *args, **kwargs)

        def map_option(self, *args, **kwargs):
            order.append('map_option')
            return False

        app = self.app()
        with patch.object(StatusLoopApp, 'handle_battle_status', battle_status), \
                patch.object(StatusLoopApp, 'handle_auto_search_map_option', map_option):
            app.auto_search_combat_status()
        self.assertTrue(order, 'no handler was asked on the archived frame')
        self.assertEqual(order[0], 'battle_status')
        self.assertEqual(list(app.device.click_record), ['BATTLE_STATUS_S'])


if __name__ == '__main__':
    unittest.main()
