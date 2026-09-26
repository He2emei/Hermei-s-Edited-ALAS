"""The operation siren settlement screen met by the loops that are not the auto search combat loop.

Live 2026-09-26 22:46:39, dump log/error/1790433999346 (profile alas2, task OpsiHazard1Leveling):
the task entered the operation siren map of NA海域西南B, clicked the action point counter in
ActionPointHandler.action_point_enter() (22:45:19.942, ACTION_POINT_REMAIN_OS) and then waited sixty
seconds while the settlement screen of a finished battle covered the display - `GameStuckError: Wait
too long` at 22:46:39.344.  The loop that was running knows only the first half of the post-battle
flow: `handle_battle_result_screen()` skipped the campaign result screen (22:45:37.103 and
22:45:39.172, both clicks landing on the blue 战斗记录 button of this layout, which is the button
area of BATTLE_STATUS_*), and the rank letters of the settlement layout (EXP_INFO_*) are wired into
AutoSearchCombat.auto_search_combat() only.

The archived frame is tests/fixtures/opsi_settlement_map_event/exp-settlement-2246.png (verbatim
copy of the dump).  The map frame the loops are expected to end on is the archived frame of the same
zone, tests/fixtures/battle_result/os-map-cleared.png, the campaign result screen that precedes this
layout is tests/fixtures/battle_result/result-s-1551.png, and the page_main screenshots that ship
with the assets (assets/cn/ui/MAIN_GOTO_FLEET.png, assets/cn/ui_white/MAIN_GOTO_CAMPAIGN_WHITE.png)
are the frames the page_main guard is measured on.
"""
import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.base.utils import get_color
from module.combat import battle_result
from module.combat.assets import (BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D,
                                  BATTLE_STATUS_S, EXP_INFO_S, QUIT_RECONFIRM)
from module.combat.battle_result import (SETTLEMENT_MAX_ATTEMPT, handle_settlement_screen,
                                         match_combat_hud_button, match_combat_quit_button,
                                         match_settlement_button)
from module.handler.info_handler import InfoHandler
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import IN_MAP
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import MAIN_GOTO_FLEET
from module.ui.page import page_os
from module.ui.ui import UI
from module.ui_white.assets import MAIN_GOTO_CAMPAIGN_WHITE

from tests.test_battle_result_skip import ClickContractDevice

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/opsi_settlement_map_event'
BATTLE_RESULT_FIXTURES = ROOT / 'tests/fixtures/battle_result'
ASSETS = ROOT / 'assets/cn'

SETTLEMENT = 'exp-settlement-2246'
MAP = 'os-map-cleared'
CAMPAIGN_RESULT = 'result-s-1551'
PAGE_MAIN = ASSETS / 'ui/MAIN_GOTO_FLEET.png'
PAGE_MAIN_WHITE = ASSETS / 'ui_white/MAIN_GOTO_CAMPAIGN_WHITE.png'

# Recognition signal of the settlement screen, the click target of the same asset (确定), and the
# click target of the campaign layout (点击继续, the blue 战斗记录 button on the settlement layout).
RANK_AREA = (342, 107, 389, 119)
CONFIRM_AREA = (1133, 634, 1262, 650)
CAMPAIGN_SKIP_AREA = (1000, 631, 1055, 689)


def image(name):
    if name == MAP or name == CAMPAIGN_RESULT:
        return np.asarray(Image.open(BATTLE_RESULT_FIXTURES / (name + '.png')).convert('RGB'))
    if name == 'page_main':
        return np.asarray(Image.open(PAGE_MAIN).convert('RGB'))
    if name == 'page_main_white':
        return np.asarray(Image.open(PAGE_MAIN_WHITE).convert('RGB'))
    return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))


def with_rank_letter(frame, button=EXP_INFO_S):
    """Paint the recognition signal of the settlement screen onto a frame that lacks it.

    The guard of the handler is what has to keep such a frame unclicked, so the rank letter area is
    filled with the colour the asset expects (a colour probe, `Button.appear_on()`).
    """
    frame = frame.copy()
    x1, y1, x2, y2 = button.area
    frame[y1:y2, x1:x2] = button.color
    return frame


def clear():
    battle_result.settlement_click_timer.reset()
    battle_result.settlement_click_timer._start = 0
    battle_result.settlement_attempt = 0


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class SettlementScreenFrameTest(unittest.TestCase):
    """What the archived frame of this incident really holds."""

    def frame(self):
        return image(SETTLEMENT)

    def test_the_crash_frame_is_the_settlement_screen(self):
        frame = self.frame()
        self.assertIs(match_settlement_button(frame), EXP_INFO_S)
        # The rank letter is the recognition signal, the button of the same asset is 确定.
        self.assertEqual(tuple(EXP_INFO_S.area), RANK_AREA)
        self.assertEqual(tuple(EXP_INFO_S.button), CONFIRM_AREA)
        color = get_color(frame, CONFIRM_AREA)
        # Measured (219, 145, 43): the orange confirm button, and the colour is stable over the
        # 78 archived settlement frames (207..243, 144..171, 40..79).
        self.assertGreater(color[0], 180)
        self.assertGreater(color[0], color[1])
        self.assertGreater(color[1], color[2])

    def test_the_frame_is_not_the_map_nor_a_running_combat(self):
        """Why the loop could neither end nor click: no handler of it matched this frame."""
        frame = self.frame()
        self.assertFalse(IN_MAP.match_luma(frame, offset=(200, 5)))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(frame, offset=(5, 5)))
        # The campaign layout that handle_battle_result_screen() knows is the other half of the
        # flow: its rank letter is at (643, 297, 722, 317) and its click target is the blue
        # 战斗记录 button of this layout, measured (112, 151, 200) here.
        for button in (BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D):
            with self.subTest(button=button.name):
                self.assertFalse(button.appear_on(frame))
        self.assertEqual(tuple(BATTLE_STATUS_S.button), CAMPAIGN_SKIP_AREA)
        self.assertGreater(get_color(frame, CAMPAIGN_SKIP_AREA)[2], 180)
        # The battle HUD sequence of the page poll is not this screen either.
        self.assertIsNone(match_combat_hud_button(frame))
        self.assertIsNone(match_combat_quit_button(frame))
        self.assertFalse(QUIT_RECONFIRM.match_luma(frame, offset=(20, 20)))

    def test_the_main_page_guard_is_quiet_on_the_settlement_screen(self):
        """The guard must not cost the recall of the screen it is there for."""
        frame = self.frame()
        self.assertFalse(MAIN_GOTO_FLEET.appear_on(frame))
        self.assertFalse(MAIN_GOTO_CAMPAIGN_WHITE.appear_on(frame))

    def test_the_campaign_result_screen_is_not_the_settlement_screen(self):
        frame = image(CAMPAIGN_RESULT)
        self.assertIsNone(match_settlement_button(frame))
        self.assertTrue(BATTLE_STATUS_S.appear_on(frame))

    def test_the_map_is_not_the_settlement_screen(self):
        self.assertIsNone(match_settlement_button(image(MAP)))


class SettlementScreenGuardTest(unittest.TestCase):
    """The page_main guard of the handler, on the screenshots that ship with the assets."""

    def test_the_page_main_frames_are_recognized_as_page_main(self):
        self.assertTrue(MAIN_GOTO_FLEET.appear_on(image('page_main')))
        self.assertTrue(MAIN_GOTO_CAMPAIGN_WHITE.appear_on(image('page_main_white')))

    def test_a_main_page_is_not_clicked_even_with_the_rank_letter(self):
        """page_main's random background is what upstream keeps this probe away from."""
        for name in ('page_main', 'page_main_white'):
            with self.subTest(frame=name):
                frame = with_rank_letter(image(name))
                # The painted rank letter is what the handler looks for ...
                self.assertTrue(EXP_INFO_S.appear_on(frame))
                # ... and the guard is what keeps it unclicked.
                self.assertIsNone(match_settlement_button(frame))
                clear()
                app = SimpleNamespace(device=ClickContractDevice(frame))
                self.assertFalse(handle_settlement_screen(app))
                self.assertEqual(app.device.clicked, [])

    def test_the_rank_letter_alone_is_clicked_on_any_other_screen(self):
        """The same painted frame without a main page is clicked, so the guard is the difference."""
        frame = with_rank_letter(image(SETTLEMENT))
        self.assertIs(match_settlement_button(frame), EXP_INFO_S)


class MapEventApp:
    """The Alas instance MapEventHandler.handle_map_event() needs, with the real module code bound."""

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
    get_interval_timer = ModuleBase.get_interval_timer
    interval_reset = ModuleBase.interval_reset
    interval_clear = ModuleBase.interval_clear
    match_template_color = ModuleBase.match_template_color
    image_crop = ModuleBase.image_crop
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

    _popup_offset = (3, 30)

    def __init__(self, frame):
        self.device = ClickContractDevice(frame)
        self.interval_timer = {}
        self.map_is_threat_safe = True
        self._hot_fix_check_wait = Timer(6)
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main')

    def __getattr__(self, item):
        # The remaining popup handlers of the loop are not what this test is about.
        return lambda *args, **kwargs: False


class MapEventLoopTest(unittest.TestCase):
    """The operation siren loops that wait for the map through handle_map_event()."""

    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_loop_clicks_the_settlement_screen(self):
        app = MapEventApp(image(SETTLEMENT))
        self.assertEqual(app.handle_map_event(), 'settlement')
        self.assertEqual(list(app.device.click_record), ['EXP_INFO_S'])
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], CONFIRM_AREA)

    def test_the_loop_leaves_the_map_and_the_result_screen_alone(self):
        app = MapEventApp(image(MAP))
        self.assertEqual(app.handle_map_event(), '')
        self.assertEqual(app.device.clicked, [])

        app = MapEventApp(image(CAMPAIGN_RESULT))
        self.assertEqual(app.handle_map_event(), 'battle_result')
        self.assertEqual(list(app.device.click_record), ['BATTLE_STATUS_S'])
        self.assert_in_area(app.device.clicked[0], CAMPAIGN_SKIP_AREA)

    def test_the_loop_does_not_click_a_main_page(self):
        app = MapEventApp(with_rank_letter(image('page_main')))
        self.assertEqual(app.handle_map_event(), '')
        self.assertEqual(app.device.clicked, [])

    def test_the_clicks_of_one_screen_are_bounded(self):
        """A screen the game ignores keeps the loop on the stuck check it had before."""
        app = MapEventApp(image(SETTLEMENT))
        for _ in range(10):
            battle_result.settlement_click_timer.reset()
            battle_result.settlement_click_timer._start = 0
            handle_settlement_screen(app)
        self.assertEqual(len(app.device.clicked), SETTLEMENT_MAX_ATTEMPT)
        for point in app.device.clicked:
            self.assert_in_area(point, CONFIRM_AREA)
        # The click guard of the device is never reached on that state.
        self.assertLess(SETTLEMENT_MAX_ATTEMPT, 12)

    def test_a_screen_that_disappears_resets_the_attempts(self):
        app = MapEventApp(image(SETTLEMENT))
        battle_result.settlement_click_timer.reset()
        battle_result.settlement_click_timer._start = 0
        self.assertTrue(handle_settlement_screen(app))
        app.device.image = image(MAP)
        self.assertFalse(handle_settlement_screen(app))
        app.device.image = image(SETTLEMENT)
        battle_result.settlement_click_timer.reset()
        battle_result.settlement_click_timer._start = 0
        self.assertTrue(handle_settlement_screen(app))
        self.assertEqual(len(app.device.clicked), 2)


class PagePollApp:
    """The UI instance UI.ui_get_current_page() needs, with the real module code bound to it.

    Same stand-in as tests/test_combat_hud_page_unknown.py: the device serves a scripted sequence of
    frames and moves on every few screenshots, so a poll that cannot leave a state fails the test
    instead of spinning.
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
        if self.screenshots % self.hold == 0 and self.index + 1 < len(self.frames):
            self.index += 1
            self.device.image = image(self.frames[self.index])
        return self.device.image

    # The rest of the page poll is not the subject of this test.
    def ui_additional(self, get_ship=True):
        return False

    def handle_login_page(self, interval=3):
        return False


class PagePollTest(unittest.TestCase):
    """The page poll of a scheduler that starts while the settlement screen is on the display."""

    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_the_poll_closes_the_settlement_screen_instead_of_reporting_the_page(self):
        app = PagePollApp([SETTLEMENT, SETTLEMENT, SETTLEMENT, MAP], hold=3)
        page = app.ui_get_current_page()
        self.assertIs(page, page_os)
        self.assertEqual(list(app.device.click_record), ['EXP_INFO_S'])
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_handler_the_poll_reports_the_page(self):
        """The pre-fix behaviour of the same frame, for the record.

        160 archived dumps reached this branch and 7 of their frames are this screen (2025-12-10,
        2026-01-10 x2, 2026-06-10, 2026-08-28, 2026-08-29, 2026-09-18), all `Game page unknown`.
        """
        from module.exception import GamePageUnknownError
        app = PagePollApp([SETTLEMENT], hold=1, limit=2000)
        with patch('module.ui.ui.handle_settlement_screen', lambda app: False):
            with self.assertRaises(GamePageUnknownError):
                app.ui_get_current_page()
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
