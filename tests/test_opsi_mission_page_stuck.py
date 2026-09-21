import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.battle_result import match_battle_result_button
from module.device.control import Control
from module.handler.info_handler import InfoHandler
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                      AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD, IN_MAP, MISSION_CHECK,
                                      MISSION_CHECKOUT, MISSION_QUIT)
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import MapEventHandler

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/opsi_mission_page'
# Operation siren map frame of an earlier incident, already archived for the result screen test.
MAP_FRAME = ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'


class ClickContractDevice:
    """A stand-in device that clicks through the real `Control.click()`.

    `Control.click()` takes a Button and reads `button.button`, so the point of the click is
    recorded by `click_adb()`, the last step of the real method.
    """

    click = Control.click

    def __init__(self, image, on_click=None):
        self.image = image
        self.on_click = on_click
        self.clicked = []
        self.click_record = collections.deque(maxlen=20)
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB')

    @property
    def click_methods(self):
        return {'ADB': self.click_adb}

    def click_adb(self, x, y):
        self.clicked.append((x, y))
        if self.on_click is not None:
            self.on_click()

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record.append(str(button))

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def stuck_record_add(self, button):
        pass


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class MapEventLoopApp:
    """The Alas instance the operation siren map loops need, with the real module code bound.

    Only the device is a stand-in: it serves the archived frames, moves from the operation info
    page to the map when a click arrives, and stops the loop after `limit` screenshots so a loop
    that cannot advance fails the test instead of spinning forever.
    """

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
    interval_reset = ModuleBase.interval_reset
    interval_clear = ModuleBase.interval_clear
    match_template_color = ModuleBase.match_template_color
    image_crop = ModuleBase.image_crop
    loop = ModuleBase.loop
    is_in_map = OsEnemySearchingHandler.is_in_map
    handle_map_event = MapEventHandler.handle_map_event
    handle_os_mission_page = MapEventHandler.handle_os_mission_page
    handle_map_get_items = MapEventHandler.handle_map_get_items
    handle_os_game_tips = MapEventHandler.handle_os_game_tips
    handle_map_archives = MapEventHandler.handle_map_archives
    handle_ash_popup = MapEventHandler.handle_ash_popup
    handle_guild_popup_cancel = InfoHandler.handle_guild_popup_cancel
    handle_urgent_commission = InfoHandler.handle_urgent_commission
    handle_story_skip = InfoHandler.handle_story_skip
    handle_os_in_map = MapEventHandler.handle_os_in_map
    ensure_no_map_event = MapEventHandler.ensure_no_map_event

    _popup_offset = (3, 30)

    def __init__(self, page_frame, map_frame, limit=4000):
        self.frames = (page_frame, map_frame)
        self.limit = limit
        self.screenshots = 0
        self.interval_timer = {}
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main')
        self.map_is_threat_safe = True
        self._os_in_map_confirm_timer = Timer(1.5, count=3)
        self._hot_fix_check_wait = Timer(6)
        self.device = ClickContractDevice(page_frame, on_click=self.leave_mission_page)
        self.device.screenshot = self.screenshot

    def leave_mission_page(self):
        # The game closes the operation info page and shows the map once MISSION_QUIT is clicked.
        self.device.image = self.frames[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no exit after {self.limit} screenshots')
        return self.device.image


class OsMissionPageTest(unittest.TestCase):
    """The operation info page that hung OpsiMeowfficerFarming on 2026-09-21 23:06:47.

    Live dump log/error/1790003207571: the auto search loop of zone 144 turned auto search on at
    23:05:46.103, the frame of 23:05:46.779 matched BATTLE_STATUS_C, and the skip target of that
    asset, (1000, 631, 1055, 689), is inside the yellow `情报` button of the map (the button blob of
    the archived frame spans x=915..1029, y=635..700, the click point is (1027, 661)). The click
    opened the operation info page, which no operation siren map loop handles: the loop polled the
    map event buttons for sixty seconds and the stuck check of the device ended the task with
    `GameStuckError: Wait too long`.

    The same page trapped storage_enter() 36 times on 2026-08-29 (dumps log/error/1787941386485 to
    1787979603420, all `GameStuckError` with the same poll set), which the earlier fix recovered in
    os_globe_goto_map() and storage_enter() only.
    """

    def image(self, path):
        return np.asarray(Image.open(path).convert('RGB'))

    def mission_page(self):
        return self.image(EVIDENCE / 'mission-page-2306.png')

    def map_frame(self):
        return self.image(MAP_FRAME)

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_hang_frame_has_no_exit_for_the_map_loops(self):
        """Nothing the auto search loop polls matched, which is why it could never advance."""
        image = self.mission_page()
        # The page itself, recognized by the close button os_mission_quit() clicks.
        self.assertTrue(MISSION_QUIT.match(image, offset=(20, 20)))
        self.assertTrue(MISSION_CHECK.appear_on(image))
        self.assertTrue(MISSION_CHECKOUT.appear_on(image))
        # Everything the loop of the dump polled before it gave up.
        self.assertFalse(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(image, offset=(5, 5)))
        for button in (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                       AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD):
            with self.subTest(button=str(button)):
                self.assertFalse(button.match_template_color(image, offset=(50, 50))
                                 if button is AUTO_SEARCH_REWARD
                                 else button.match_template_color(image, offset=(5, 120)))
        self.assertIsNone(match_battle_result_button(image))

    def test_map_event_closes_the_mission_page(self):
        app = MapEventLoopApp(self.mission_page(), self.map_frame())
        self.assertEqual(MapEventHandler.handle_map_event(app), 'os_mission_page')
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], MISSION_QUIT.button)
        self.assertEqual(list(app.device.click_record), ['MISSION_QUIT'])

    def test_map_event_leaves_the_map_frame_alone(self):
        app = MapEventLoopApp(self.mission_page(), self.map_frame())
        app.device.image = self.map_frame()
        self.assertFalse(MapEventHandler.handle_map_event(app))
        self.assertEqual(app.device.clicked, [])

    def test_the_map_loop_ends_after_the_mission_page_is_closed(self):
        """ensure_no_map_event() reaches the map again instead of waiting for the stuck check."""
        app = MapEventLoopApp(self.mission_page(), self.map_frame())
        app.ensure_no_map_event()
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], MISSION_QUIT.button)
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_mission_page_handler_the_map_loop_never_ends(self):
        """The pre-fix behaviour of the same frames, for the record."""
        app = MapEventLoopApp(self.mission_page(), self.map_frame(), limit=50)
        # The harness binds the handler, so the pre-fix behaviour is the harness without it.
        with patch.object(MapEventLoopApp, 'handle_os_mission_page', lambda self: False):
            with self.assertRaises(LoopLimitReached):
                app.ensure_no_map_event()
        self.assertEqual(app.device.clicked, [])

    def test_the_map_frame_is_the_end_condition(self):
        """The map frame of the loop test really is an is_in_map() frame."""
        image = self.map_frame()
        self.assertTrue(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertFalse(MISSION_QUIT.match(image, offset=(20, 20)))


if __name__ == '__main__':
    unittest.main()
