import collections
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.battle_result import match_battle_result_button
from module.device.control import Control
from module.handler.assets import INFO_BAR_1
from module.handler.info_handler import InfoHandler
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                      AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD, IN_MAP, MISSION_QUIT)
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import GLOBE_GOTO_MAP, STORAGE_CHECK, MapEventHandler

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/auto_search_quit_info_bar'
# Operation siren map frame of the same zone (NA海域西南B), already archived for the result screen
# test. It is the end condition os_auto_search_quit() waits for, is_in_map().
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


class QuitLoopApp:
    """The Alas instance `os_auto_search_quit()` needs, with the real module code bound to it.

    Only the device is a stand-in: it serves the archived frames, moves from the reward panel to
    the map when a click arrives, and stops the loop after `limit` screenshots so a loop that
    cannot advance fails the test instead of spinning forever.
    """

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
    interval_reset = ModuleBase.interval_reset
    interval_clear = ModuleBase.interval_clear
    match_template_color = ModuleBase.match_template_color
    image_crop = ModuleBase.image_crop
    loop = ModuleBase.loop
    info_bar_count = InfoHandler.info_bar_count
    handle_info_bar = InfoHandler.handle_info_bar
    ensure_no_info_bar = InfoHandler.ensure_no_info_bar
    wait_until_info_bar_disappear = InfoHandler.wait_until_info_bar_disappear
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
    os_auto_search_quit = MapEventHandler.os_auto_search_quit

    _popup_offset = (3, 30)

    def __init__(self, reward_frame, map_frame, limit=4000):
        self.frames = (reward_frame, map_frame)
        self.limit = limit
        self.screenshots = 0
        self.interval_timer = {}
        self.map_is_threat_safe = True
        self._hot_fix_check_wait = Timer(6)
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main')
        self.device = ClickContractDevice(reward_frame, on_click=self.leave_reward_panel)
        self.device.screenshot = self.screenshot

    def leave_reward_panel(self):
        # The game closes the reward panel and shows the map once 离开 is clicked.
        self.device.image = self.frames[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no exit after {self.limit} screenshots')
        return self.device.image


class OsAutoSearchQuitInfoBarTest(unittest.TestCase):
    """The reward panel that hung OpsiHazard1Leveling on 2026-09-22 14:16:13.

    Live dump log/error/1790057773446. The auto search loop of zone 22 turned auto search on at
    14:15:07.862, the game answered with the 合计获得奖励 reward panel (its 离开 button is
    AUTO_SEARCH_REWARD) and with the info bar `当前所选舰队视野内无可自律事件，无法继续自律寻敌`
    (no auto searchable event in the vision of the selected fleet), and nothing else happened for
    sixty seconds: `os_auto_search_quit()` waited for the info bar to disappear before clicking the
    reward panel, while the info bar is kept on the display by that very panel. The stack of the
    dump ends in wait_until_info_bar_disappear() -> device.screenshot(), and the archived frame
    still holds the bar, so the wait could never end and the stuck check of the device raised
    `GameStuckError: Wait too long`.

    `reward-with-info-bar-1416.png` is the archived frame of that dump. The info bar is the same
    asset the other loops count (`INFO_BAR_1`, the blue line on top of the bar at y=297..299, the
    peak of info_bar_count() is 251 against a threshold of 235), so no new template is assumed here.
    """

    def image(self, path):
        return np.asarray(Image.open(path).convert('RGB'))

    def reward_frame(self):
        return self.image(EVIDENCE / 'reward-with-info-bar-1416.png')

    def map_frame(self):
        return self.image(MAP_FRAME)

    def app(self, limit=4000):
        return QuitLoopApp(self.reward_frame(), self.map_frame(), limit=limit)

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_hang_frame_holds_the_reward_panel_and_an_info_bar(self):
        """The two things of the dump frame: the panel to click and the bar that was waited for."""
        image = self.reward_frame()
        self.assertTrue(AUTO_SEARCH_REWARD.match(image, offset=(50, 50)))
        self.assertTrue(INFO_BAR_1.appear_on(image))
        self.assertEqual(self.app().info_bar_count(), 1)
        # The click target is below the bar, so the bar cannot swallow the click that dismisses
        # the panel it belongs to.
        self.assertGreater(AUTO_SEARCH_REWARD.button[1], INFO_BAR_1.area[3])

    def test_the_hang_frame_has_no_other_exit_for_the_quit_loop(self):
        """Nothing else the quit loop polls matched, which is why the panel click had to happen."""
        image = self.reward_frame()
        self.assertIsNone(match_battle_result_button(image))
        for button, offset in ((MISSION_QUIT, (20, 20)), (GLOBE_GOTO_MAP, (20, 20)),
                               (STORAGE_CHECK, (20, 20))):
            with self.subTest(button=str(button)):
                self.assertFalse(button.match(image, offset=offset))
        for button in (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                       AUTO_SEARCH_OS_MAP_OPTION_ON):
            with self.subTest(button=str(button)):
                self.assertFalse(button.match_template_color(image, offset=(5, 120)))
        # is_in_map(), the end condition of the loop.
        self.assertFalse(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(image, offset=(5, 5)))

    def test_the_quit_loop_dismisses_the_panel_with_the_info_bar_up(self):
        """os_auto_search_quit() clicks 离开 instead of waiting for the bar of that panel."""
        app = self.app()
        self.assertTrue(app.os_auto_search_quit())
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], AUTO_SEARCH_REWARD.button)
        self.assertEqual(list(app.device.click_record), ['AUTO_SEARCH_REWARD'])
        self.assertLess(app.screenshots, app.limit)

    def test_the_wait_the_fix_removed_can_never_end_on_this_frame(self):
        """The pre-fix call of the quit loop, for the record.

        `os_auto_search_quit()` used to call `ensure_no_info_bar()` before clicking the reward
        panel. The bar stays on the display while that panel is open, so the call polls the same
        picture and the sixty second stuck check of the device ends the task.
        """
        app = self.app(limit=50)
        with self.assertRaises(LoopLimitReached):
            app.ensure_no_info_bar()
        self.assertEqual(app.device.clicked, [])

    def test_the_same_wait_ends_on_a_map_frame(self):
        """The unbounded wait itself, on a map frame, so the test above is about the bar."""
        app = self.app(limit=50)
        app.device.image = self.map_frame()
        app.wait_until_info_bar_disappear()
        self.assertEqual(app.screenshots, 1)

    def test_the_map_frame_is_the_end_condition(self):
        """The map frame of the loop test really is an is_in_map() frame."""
        image = self.map_frame()
        self.assertTrue(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertFalse(AUTO_SEARCH_REWARD.match(image, offset=(50, 50)))
        self.assertFalse(INFO_BAR_1.appear_on(image))


if __name__ == '__main__':
    unittest.main()
