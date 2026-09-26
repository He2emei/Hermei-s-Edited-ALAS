import collections
import unittest
from contextlib import contextmanager
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
                                  BATTLE_STATUS_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D, EXP_INFO_S)
from module.combat.combat import Combat
from module.device.control import Control
from module.handler.info_handler import InfoHandler
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_combat.combat import Combat as OsCombat
from module.os_handler.assets import (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                      AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD, IN_MAP)
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import GLOBE_GOTO_MAP, STORAGE_CHECK, MapEventHandler

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/auto_search_exp_settlement'
# An operation siren map frame of the same zone (NA海域西南B), the end condition of the loop.
MAP_FRAME = ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'

# Recognition signal of the settlement screen and the click target of the same asset.
EXP_INFO_S_AREA = (342, 107, 389, 119)
CONFIRM_AREA = (1133, 634, 1262, 650)
# Clickable area of the campaign result screen, which is the battle log button on this layout.
CAMPAIGN_SKIP_AREA = (1000, 631, 1055, 689)


def image(path):
    return np.asarray(Image.open(path).convert('RGB'))


@contextmanager
def fresh_click_state():
    """Reset the module level click state of the battle result handler."""
    battle_result.battle_result_click_timer.reset()
    battle_result.battle_result_click_timer._start = 0
    battle_result.battle_result_attempt = 0
    battle_result.battle_result_clicked_at = 0.
    try:
        yield
    finally:
        battle_result.battle_result_click_timer.reset()
        battle_result.battle_result_click_timer._start = 0
        battle_result.battle_result_attempt = 0
        battle_result.battle_result_clicked_at = 0.


class ClickContractDevice:
    """A stand-in device that clicks through the real `Control.click()`.

    `Control.click()` takes a Button, not a coordinate, so the stand-in keeps that contract and
    records the button name and the point of the click.
    """

    click = Control.click

    def __init__(self, frame, on_click=None, screenshot_limit=5000):
        self.image = frame
        self.on_click = on_click
        self.screenshot_limit = screenshot_limit
        self.clicked = []
        self.screenshots = 0
        self.click_record = collections.deque(maxlen=20)
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB')

    @property
    def click_methods(self):
        return {'ADB': self.click_adb}

    def click_adb(self, x, y):
        self.clicked.append((x, y))
        if self.on_click is not None:
            self.on_click()

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


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class SettlementScreenFrameTest(unittest.TestCase):
    def test_visible_opsi_map_is_not_treated_as_battle_result(self):
        class VisibleMap:
            def is_in_map(self):
                return True

            def __getattr__(self, name):
                return lambda *args, **kwargs: False

        with patch('module.os_handler.map_event.handle_battle_result_screen',
                   side_effect=AssertionError('must not inspect settlement on visible map')):
            self.assertEqual(MapEventHandler.handle_map_event(VisibleMap()), '')

    """The screen that hung OpsiHazard1Leveling on 2026-09-22 02:56:34.

    Live log/error/1790016994804 (plus 1789999429360, 1790004710224, 1790005453134 and
    1790012911841 in the same night, all with the same traceback and the same `Waiting for` set):
    the archived frame is the post-battle settlement screen of an operation siren auto search
    battle, 大获全胜 S + the EXP list of the fleet + the orange 确定 button.  The traceback ends in
    `module/os_combat/combat.py:262 auto_search_combat()`, the loop that watches the battle, so
    the loop itself has to click that screen away.
    """

    def frame(self):
        return image(EVIDENCE / 'exp-settlement-0256.png')

    def test_the_archived_frame_is_the_settlement_screen(self):
        frame = self.frame()
        self.assertTrue(EXP_INFO_S.appear_on(frame))
        # The rank letter is the recognition signal, the button of the same asset is 确定.
        self.assertEqual(tuple(EXP_INFO_S.area), EXP_INFO_S_AREA)
        self.assertEqual(tuple(EXP_INFO_S.button), CONFIRM_AREA)
        color = get_color(frame, CONFIRM_AREA)
        # Measured (220.0, 146.5, 44.4) on the archived frame: the orange confirm button.
        self.assertGreater(color[0], 180)
        self.assertGreater(color[0], color[1])
        self.assertGreater(color[1], color[2])

    def test_the_frame_is_not_the_map_nor_a_running_combat(self):
        """Why the loop could neither end nor click: no handler of it matched this frame."""
        frame = self.frame()
        self.assertFalse(IN_MAP.match_luma(frame, offset=(200, 5)))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(frame, offset=(5, 5)))
        for button in (BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D):
            with self.subTest(button=button.name):
                self.assertFalse(button.appear_on(frame))
        for button in (EXP_INFO_C, EXP_INFO_D):
            with self.subTest(button=button.name):
                self.assertFalse(button.appear_on(frame))
        self.assertFalse(AUTO_SEARCH_REWARD.match(frame, offset=(50, 50)))
        self.assertFalse(AUTO_SEARCH_OS_MAP_OPTION_OFF.match_template_color(frame, offset=(5, 120)))
        self.assertFalse(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED.match_template_color(frame, offset=(5, 120)))
        self.assertFalse(AUTO_SEARCH_OS_MAP_OPTION_ON.match_template_color(frame, offset=(5, 120)))
        # Combat.is_combat_executing() registers PAUSE in the stuck record of the device, which is
        # what deferred the sixty second stuck check of the loop to 180 seconds (02:53:34.413 click
        # -> 02:56:34.803 GameStuckError).  The frame itself is not a running combat.
        app = SimpleNamespace(device=SimpleNamespace(image=frame, stuck_record_add=lambda button: None),
                              config=SimpleNamespace(SERVER='cn'),
                              image_crop=ModuleBase.image_crop)
        self.assertFalse(Combat.is_combat_executing(app))

    def test_the_click_target_of_the_campaign_layout_is_a_different_button(self):
        """The 02:53:34 click of the campaign layout landed on the battle log button."""
        frame = self.frame()
        self.assertEqual(tuple(BATTLE_STATUS_S.button), CAMPAIGN_SKIP_AREA)
        color = get_color(frame, CAMPAIGN_SKIP_AREA)
        # Measured (112.1, 151.5, 200.7): the blue 战斗记录 button, not 确定.
        self.assertGreater(color[2], color[0])
        self.assertGreater(color[2], 180)


class SettlementHandlerApp:
    """Only the real `appear()` / `appear_then_click()` chain and the stand-in device are needed."""

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button

    def __init__(self, frame):
        self.device = ClickContractDevice(frame)
        self.interval_timer = {}
        self.config = SimpleNamespace(BUTTON_OFFSET=30)

    @property
    def _auto_search_exp_info_buttons(self):
        # Read through the class, so patching the class is the pre-fix button set.
        return OsCombat._auto_search_exp_info_buttons


class SettlementHandlerTest(unittest.TestCase):
    """`handle_auto_search_exp_info()` of the operation siren auto search loop."""

    def app(self, frame):
        return SettlementHandlerApp(frame)

    def test_the_settlement_screen_is_clicked(self):
        app = self.app(image(EVIDENCE / 'exp-settlement-0256.png'))
        self.assertTrue(OsCombat.handle_auto_search_exp_info(app))
        self.assertEqual(list(app.device.click_record), ['EXP_INFO_S'])
        self.assertEqual(len(app.device.clicked), 1)
        x, y = app.device.clicked[0]
        self.assertTrue(CONFIRM_AREA[0] <= x <= CONFIRM_AREA[2], f'x of {(x, y)} is outside {CONFIRM_AREA}')
        self.assertTrue(CONFIRM_AREA[1] <= y <= CONFIRM_AREA[3], f'y of {(x, y)} is outside {CONFIRM_AREA}')

    def test_a_map_frame_is_left_alone(self):
        app = self.app(image(MAP_FRAME))
        self.assertFalse(OsCombat.handle_auto_search_exp_info(app))
        self.assertEqual(app.device.clicked, [])

    def test_the_pre_fix_button_set_never_clicked_this_frame(self):
        """The C/D only set of dfd334736 is what the S/A/B rank of the screen fell through."""
        app = self.app(image(EVIDENCE / 'exp-settlement-0256.png'))
        with patch.object(OsCombat, '_auto_search_exp_info_buttons', (EXP_INFO_C, EXP_INFO_D)):
            self.assertFalse(OsCombat.handle_auto_search_exp_info(app))
        self.assertEqual(app.device.clicked, [])


class AutoSearchLoopApp:
    """The Alas instance `Combat.auto_search_combat()` needs, with the real module code bound.

    Only the device is a stand-in: it serves the settlement frame, leaves it for the map frame when
    the 确定 click arrives and stops the loop after `limit` screenshots, so a loop that cannot
    advance fails the test instead of spinning forever.  The battle that just ended is stubbed by
    a one-shot `is_combat_executing()` (live log: `[BattleUI] PAUSE_Star` -> `Auto Search combat
    execute` -> the settlement screen).
    """

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
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
    handle_os_auto_search_map_option = MapEventHandler.handle_os_auto_search_map_option
    handle_guild_popup_cancel = InfoHandler.handle_guild_popup_cancel
    handle_urgent_commission = InfoHandler.handle_urgent_commission
    handle_story_skip = InfoHandler.handle_story_skip
    handle_auto_search_battle_status = OsCombat.handle_auto_search_battle_status
    handle_auto_search_exp_info = OsCombat.handle_auto_search_exp_info
    auto_search_combat = OsCombat.auto_search_combat

    battle_status_click_interval = Combat.battle_status_click_interval
    _popup_offset = (3, 30)

    def __init__(self, settlement_frame, map_frame, limit=5000):
        self.frames = (settlement_frame, map_frame)
        self.in_combat = True
        self.interval_timer = {}
        self.map_is_threat_safe = True
        self._hot_fix_check_wait = Timer(6)
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main',
                                      Submarine_Fleet=False, Submarine_Mode='do_not_use')
        self.device = ClickContractDevice(settlement_frame, on_click=self.leave_settlement_screen,
                                          screenshot_limit=limit)

    @property
    def _auto_search_exp_info_buttons(self):
        return OsCombat._auto_search_exp_info_buttons

    def __getattr__(self, item):
        # The remaining popup handlers of the loop are not what this test is about.
        return lambda *args, **kwargs: False

    def is_combat_executing(self):
        # The battle that just ended: the first probe of the loop sees the battle UI, the
        # settlement screen that follows is what the loop has to click.
        if self.in_combat:
            self.in_combat = False
            return 'PAUSE_Star'
        return False

    def info_bar_count(self):
        return 0

    def leave_settlement_screen(self):
        self.device.image = self.frames[1]


class AutoSearchLoopTest(unittest.TestCase):
    """`auto_search_combat()` of the operation siren auto search ends on the archived frames."""

    def settlement(self):
        return image(EVIDENCE / 'exp-settlement-0256.png')

    def map_frame(self):
        return image(MAP_FRAME)

    def test_the_loop_ends_on_the_archived_frames(self):
        app = AutoSearchLoopApp(self.settlement(), self.map_frame())
        with fresh_click_state():
            result = app.auto_search_combat()
        # The loop left the settlement screen for the map instead of waiting for the stuck check.
        self.assertLess(app.device.screenshots, app.device.screenshot_limit)
        self.assertEqual(list(app.device.click_record), ['EXP_INFO_S'])
        self.assertEqual(len(app.device.clicked), 1)
        x, y = app.device.clicked[0]
        self.assertTrue(CONFIRM_AREA[0] <= x <= CONFIRM_AREA[2], f'x of {(x, y)} is outside {CONFIRM_AREA}')
        self.assertTrue(CONFIRM_AREA[1] <= y <= CONFIRM_AREA[3], f'y of {(x, y)} is outside {CONFIRM_AREA}')
        # Clicking the settlement screen marks the battle as "state unknown" (`success = None`,
        # "Don't change auto search option if failed"), the same as the existing C/D branch of the
        # loop: the caller then checks the HP of the fleet.
        self.assertIsNone(result)

    def test_without_the_settlement_handler_the_loop_never_ends(self):
        """The pre-fix behaviour of the same frames, for the record.

        `handle_map_event()` at the end of the loop skips the same screen since 2026-09-26
        (`handle_settlement_screen()`), so that handler is stubbed out as well: this test is about
        the button set of the auto search loop itself.
        """
        app = AutoSearchLoopApp(self.settlement(), self.map_frame(), limit=50)
        with fresh_click_state(), patch.object(OsCombat, '_auto_search_exp_info_buttons',
                                               (EXP_INFO_C, EXP_INFO_D)), \
                patch('module.os_handler.map_event.handle_settlement_screen', lambda app: False):
            with self.assertRaises(LoopLimitReached):
                app.auto_search_combat()
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
