import collections
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.assets import BATTLE_STATUS_S
from module.combat import battle_result
from module.combat.battle_result import (battle_result_click_timer, handle_battle_result_screen,
                                         match_battle_result_button)
from module.device.control import Control
from module.handler.info_handler import InfoHandler
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import MapEventHandler
from module.os_handler.assets import (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                      AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD, IN_MAP)
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.map_event import GLOBE_GOTO_MAP, STORAGE_CHECK

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/battle_result'

# Clickable area of the battle result screen, shared by BATTLE_STATUS_* and GET_ITEMS_*.
SKIP_AREA = (1000, 631, 1055, 689)


def clear():
    battle_result.battle_result_click_timer.reset()
    battle_result.battle_result_click_timer._start = 0
    battle_result.battle_result_attempt = 0
    battle_result.battle_result_clicked_at = 0.


@contextmanager
def fresh_click_state():
    """Reset the module level click state of the handler, and restore it after."""
    clear()
    try:
        yield
    finally:
        clear()


class ClickContractDevice:
    """A stand-in device that clicks through the real `Control.click()`.

    `Control.click()` takes a Button, not a coordinate: it reads `button.button` and adds the button
    to the click record of the device.  A stand-in whose `click()` also accepts a bare point hides
    that contract, which is how a coordinate reached production and crashed the whole task with
    `AttributeError: 'tuple' object has no attribute 'button'` (live 2026-09-21 05:52:59, dump
    log/error/1789941179502).  The point of the click is recorded by `click_adb()`, the last step of
    the real method.
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
        # Device.handle_control_check() clears the stuck record and adds the button to the click
        # record, which is what a bare coordinate cannot serve.
        self.stuck_record_clear()
        self.click_record.append(str(button))

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def stuck_record_add(self, button):
        pass


class BattleResultFrameTest(unittest.TestCase):
    """The battle result screen that blocked GemsFarming on 2026-09-20.

    Live 15:48:25 and 15:51:12, both CRITICAL `Game page unknown`: the scheduler had been
    restarted while a battle of event a3 was running, so the display kept the result screen.
    The archived frames are the error dumps log/error/1789890505865 and 1789890672420.
    Nothing in UI.ui_get_current_page() skips a result screen, so the ten second page poll
    ended in GamePageUnknownError.
    """

    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def app(self, name, in_combat=False):
        return SimpleNamespace(
            device=ClickContractDevice(self.image(name)),
            is_combat_executing=lambda: in_combat,
        )

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_rank_button_of_the_result_screen_is_localized(self):
        for name in ('result-s-1551', 'result-s-1548', 'result-s-final'):
            with self.subTest(name=name):
                button = match_battle_result_button(self.image(name))
                self.assertIs(button, BATTLE_STATUS_S)
                # Recognition signal is the rank icon, localization is the clickable area of
                # the result screen, not the matching area of the icon.
                self.assertEqual(tuple(button.area), (643, 297, 722, 317))
                self.assertEqual(tuple(button.button), SKIP_AREA)

    def test_result_screen_is_not_detected_on_the_map(self):
        # Frame of the same stage after the result screen was clicked away.
        self.assertIsNone(match_battle_result_button(self.image('map-after-continue')))

    def test_result_screen_is_skipped_when_the_page_is_unknown(self):
        app = self.app('result-s-1551')
        with fresh_click_state():
            self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(app.device.clicked), 1)
            self.assert_in_area(app.device.clicked[0], SKIP_AREA)
            # The click timer prevents a burst of clicks while the screen switches.
            self.assertFalse(handle_battle_result_screen(app))
            self.assertEqual(len(app.device.clicked), 1)

    def test_the_click_target_is_the_button_of_the_screen(self):
        """The handler hands the Button to the device, and the click record sees it.

        `Device.click()` reads `button.button` and registers the button, so a coordinate would both
        crash here and leave the too-many-click guard of the device without a name to count.
        """
        app = self.app('result-s-1551')
        with fresh_click_state():
            self.assertTrue(handle_battle_result_screen(app))
        self.assertEqual(list(app.device.click_record), ['BATTLE_STATUS_S'])

    def test_a_still_blocked_screen_is_retried_and_then_left_alone(self):
        app = self.app('result-s-1551')
        with fresh_click_state():
            for _ in range(battle_result.BATTLE_RESULT_MAX_ATTEMPT):
                battle_result_click_timer.reset()
                battle_result_click_timer._start = 0
                self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(app.device.clicked), battle_result.BATTLE_RESULT_MAX_ATTEMPT)
            for point in app.device.clicked:
                self.assert_in_area(point, SKIP_AREA)
            # After the attempts are spent the page poll reports the page instead of clicking on.
            battle_result_click_timer.reset()
            battle_result_click_timer._start = 0
            self.assertFalse(handle_battle_result_screen(app))
            self.assertEqual(len(app.device.clicked), battle_result.BATTLE_RESULT_MAX_ATTEMPT)

    def test_a_new_battle_gets_its_own_attempts(self):
        app = self.app('result-s-1551')
        with fresh_click_state():
            battle_result.battle_result_attempt = battle_result.BATTLE_RESULT_MAX_ATTEMPT
            # No click for longer than the stale timeout: this result screen is a new battle.
            battle_result.battle_result_clicked_at = 0.
            self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(app.device.clicked), 1)

    def test_a_running_combat_is_never_clicked(self):
        app = self.app('result-s-1551', in_combat=True)
        with fresh_click_state():
            self.assertFalse(handle_battle_result_screen(app))
        self.assertEqual(app.device.clicked, [])

    def test_no_result_screen_means_no_click(self):
        app = self.app('map-after-continue')
        with fresh_click_state():
            self.assertFalse(handle_battle_result_screen(app))
        self.assertEqual(app.device.clicked, [])


class FakeMapEventApp:
    """A stand-in for the Alas instance of the operation siren map loops.

    The result screen check runs before every other map event handler, so those handlers are
    stubbed out and the click is recorded instead of being sent to an emulator.
    """

    def __init__(self, image, in_combat=False):
        self.in_combat = in_combat
        self.device = ClickContractDevice(image)
        self.combat_probe = Mock(side_effect=self._in_combat)

    def _in_combat(self):
        return self.in_combat

    def is_combat_executing(self):
        return self.combat_probe()

    def __getattr__(self, item):
        return lambda *args, **kwargs: False


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class QuitLoopApp:
    """The Alas instance `os_auto_search_quit()` needs, with the real module code bound to it.

    Only the device is a stand-in: it serves the archived frames, moves from the result screen to
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
    is_in_map = OsEnemySearchingHandler.is_in_map
    handle_map_event = MapEventHandler.handle_map_event
    handle_map_get_items = MapEventHandler.handle_map_get_items
    handle_os_game_tips = MapEventHandler.handle_os_game_tips
    handle_map_archives = MapEventHandler.handle_map_archives
    handle_ash_popup = MapEventHandler.handle_ash_popup
    handle_guild_popup_cancel = InfoHandler.handle_guild_popup_cancel
    handle_urgent_commission = InfoHandler.handle_urgent_commission
    handle_story_skip = InfoHandler.handle_story_skip
    os_auto_search_quit = MapEventHandler.os_auto_search_quit

    _popup_offset = (3, 30)

    def __init__(self, result_frame, map_frame, limit=5000):
        self.frames = (result_frame, map_frame)
        self.limit = limit
        self.screenshots = 0
        self.interval_timer = {}
        self.map_is_threat_safe = True
        self._hot_fix_check_wait = Timer(6)
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main')
        self.device = ClickContractDevice(result_frame, on_click=self.leave_result_screen)
        self.device.screenshot = self.screenshot

    def leave_result_screen(self):
        # The game leaves the result screen for the map once it is clicked.
        self.device.image = self.frames[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no exit after {self.limit} screenshots')
        return self.device.image


class OsMapEventResultScreenTest(unittest.TestCase):
    """The result screen that hung OpsiHazard1Leveling on 2026-09-20 23:08:25.

    Live log/error/1789916905429: `os_auto_search_quit()` looped over the display while the
    archived frame was a battle result screen, so the sixty second stuck check of the device ended
    in `GameStuckError: Wait too long`. Auto search had been switched off at 23:07:24 while the last
    battle was still running, so the result screen of that battle appeared afterwards, when no
    combat loop was watching it and no map event handler could click it away.

    `result-s-2308.png` is the archived frame of that dump. `os-map-cleared.png` is an operation
    siren map frame of the same zone (NA海域西南B), the end condition the loop waits for; the
    campaign map frame of the earlier incident, `map-after-continue.png`, is not one, because
    is_in_map() looks for the operation siren map buttons.
    """

    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_hang_frame_has_no_exit_for_the_quit_loop(self):
        """Nothing the quit loop polls matched, which is why it could never advance."""
        image = self.image('result-s-2308')
        # The screen itself, the recognition signal of the result screen.
        self.assertIs(match_battle_result_button(image), BATTLE_STATUS_S)
        # Everything os_auto_search_quit() checks before it gives up.
        self.assertFalse(AUTO_SEARCH_REWARD.match(image, offset=(50, 50)))
        self.assertFalse(GLOBE_GOTO_MAP.match(image, offset=(20, 20)))
        self.assertFalse(STORAGE_CHECK.match(image, offset=(20, 20)))
        # is_in_map(), the end condition of the loop.
        self.assertFalse(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(image, offset=(5, 5)))

    def test_map_event_skips_the_result_screen(self):
        app = FakeMapEventApp(self.image('result-s-2308'))
        with fresh_click_state():
            self.assertTrue(MapEventHandler.handle_map_event(app))
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], SKIP_AREA)

    def test_map_event_leaves_a_map_frame_alone(self):
        app = FakeMapEventApp(self.image('map-after-continue'))
        with fresh_click_state():
            self.assertFalse(MapEventHandler.handle_map_event(app))
        self.assertEqual(app.device.clicked, [])

    def test_a_map_frame_never_probes_for_a_running_combat(self):
        # Combat.is_combat_executing() registers PAUSE in the stuck record of the device, which
        # would drop the sixty second stuck check of a loop that has no result screen.
        app = FakeMapEventApp(self.image('map-after-continue'))
        with fresh_click_state():
            MapEventHandler.handle_map_event(app)
        self.assertEqual(app.combat_probe.call_count, 0)

    def test_a_battle_in_progress_is_not_clicked_from_the_map_event_handler(self):
        app = FakeMapEventApp(self.image('result-s-2308'), in_combat=True)
        with fresh_click_state():
            self.assertFalse(MapEventHandler.handle_map_event(app))
        self.assertEqual(app.device.clicked, [])

    def test_the_quit_loop_ends_on_the_archived_frames(self):
        """os_auto_search_quit() reaches the map again instead of waiting for the stuck check."""
        app = QuitLoopApp(self.image('result-s-2308'), self.image('os-map-cleared'))
        with fresh_click_state():
            self.assertFalse(app.os_auto_search_quit())
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], SKIP_AREA)
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_result_screen_handler_the_quit_loop_never_ends(self):
        """The pre-fix behaviour of the same frames, for the record."""
        app = QuitLoopApp(self.image('result-s-2308'), self.image('os-map-cleared'), limit=50)
        with fresh_click_state(), patch('module.os_handler.map_event.handle_battle_result_screen',
                                        lambda app: False):
            with self.assertRaises(LoopLimitReached):
                app.os_auto_search_quit()
        self.assertEqual(app.device.clicked, [])

    def test_the_os_map_frame_is_the_end_condition(self):
        """The map frame of the loop test really is an is_in_map() frame."""
        image = self.image('os-map-cleared')
        self.assertTrue(IN_MAP.match_luma(image, offset=(200, 5)))
        self.assertIsNone(match_battle_result_button(image))
        self.assertFalse(AUTO_SEARCH_REWARD.match(image, offset=(50, 50)))


if __name__ == '__main__':
    unittest.main()
