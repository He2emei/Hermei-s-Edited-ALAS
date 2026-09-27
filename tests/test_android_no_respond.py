"""The Android "application not responding" dialog that swallowed the clicks of a running task.

Live 2026-09-27 08:37:16, dump log/error/1790469436812 (profile alas2, task OpsiHazard1Leveling,
zone 22 NA海域西南B).  The game stopped answering while the 合计获得奖励 reward panel was open.
Android answered with its modal dialog `碧蓝航线没有响应 / 关闭应用 / 等待`, which is the topmost
window of the display and swallows every touch that would otherwise reach the game behind it.
`os_auto_search_quit()` kept clicking the panel's 离开 button (AUTO_SEARCH_REWARD, button area
(575, 598, 721, 646)) every 2.2 seconds, the twelve click guard of the device ended the task with
`GameTooManyClickError: Too many click for a button: AUTO_SEARCH_REWARD` and the scheduler
restarted the app.

The recognition and the localization of the reward panel were both correct on that frame
(`AUTO_SEARCH_REWARD.match(frame, offset=(50, 50))` scores 0.9948 and all eleven click points
(603..678, 606..639) are inside its button area), so nothing about the panel is changed here.

Three things of the archived frames are the subject of this test:

* the dialog is a definite state: all four dumps of this signature (1787609445464, 1790190735862,
  1790448290191, 1790469436812) hold the same dialog pixels, template score 1.0000, while the best
  of the other 1716 archived frames scores 0.3981;
* the light asset the login loop uses does not match it (0.1018 against the 0.85 threshold), so the
  handler of `_handle_app_login()` could not answer the dialog of a running task;
* the dialog is dismissed with its own 等待 row, which is the icon box (341, 433, 391, 472) of the
  same asset the login loop already used.

The intermediate frame the reward loop test needs (the panel with the dialog gone) is the archived
reward panel frame of dump 1787570393142, because every dump holds only one screenshot
(Error.ScreenshotLength = 1).
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
from module.device.control import Control
from module.device.device import Device
from module.exception import GamePageUnknownError, GameTooManyClickError
from module.handler.android_no_respond import handle_android_no_respond
from module.handler.assets import ANDROID_NO_RESPOND, ANDROID_NO_RESPOND_DARK
from module.handler.info_handler import InfoHandler
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import AUTO_SEARCH_REWARD, IN_MAP
from module.os_handler.enemy_searching import EnemySearchingHandler as OsEnemySearchingHandler
from module.os_handler.map_event import GLOBE_GOTO_MAP, STORAGE_CHECK, MapEventHandler
from module.ui.page import page_os
from module.ui.ui import UI

from tests.test_login_title_stall import HOME_FRAME, FakeLogin, FakeTimer, LoginDevice, load_frame

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/android_no_respond'
MAP_FRAME = ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'

# The dialog box of the archived frames, measured on the fill colour (27, 27, 28).
DIALOG_BOX = (312, 254, 967, 501)
# The 等待 row of the dialog, measured on the icon (350..378, 441..467) and the 等待 label.
WAIT_ROW = (330, 416, 950, 488)

NO_RESPOND = 'os-reward-no-respond-0837'
PANEL = 'os-reward-panel-1919'


def image(name):
    if name == 'map':
        return np.asarray(Image.open(MAP_FRAME).convert('RGB'))
    return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))


class ClickContractDevice:
    """A stand-in device that clicks through the real `Control.click()` and the real click guard.

    `Control.click()` takes a Button, not a coordinate, and `Device.click_record_check()` is the
    twelve click guard that ended the live task, so both are the real methods here.
    """

    click = Control.click
    handle_control_check = Device.handle_control_check
    click_record_add = Device.click_record_add
    click_record_check = Device.click_record_check

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

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def stuck_record_add(self, button):
        pass


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


class FakeClock:
    """A monotonic clock that advances a second per call, for the loops of `Timer`."""

    def __init__(self):
        self.now = 0.

    def __call__(self):
        self.now += 1.
        return self.now


class FakeApp:
    """Only the device is a stand-in; the handler runs as the real module code."""

    appear = ModuleBase.appear
    ensure_button = ModuleBase.ensure_button
    get_interval_timer = ModuleBase.get_interval_timer

    def __init__(self, frame, on_click=None):
        self.device = ClickContractDevice(frame, on_click=on_click)
        self.interval_timer = {}
        self.config = SimpleNamespace(BUTTON_OFFSET=30)


class QuitLoopApp:
    """The Alas instance `os_auto_search_quit()` needs, with the real module code bound to it.

    The device serves the archived frames: the click on the dialog takes the dialog off the
    display and leaves the reward panel, and the click on the panel closes it and shows the map,
    which is the end condition of the loop, `is_in_map()`.
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

    def __init__(self, dialog_frame, panel_frame, map_frame, answer=True, limit=4000):
        self.frames = (dialog_frame, panel_frame, map_frame)
        self.answer = answer
        self.limit = limit
        self.screenshots = 0
        self.interval_timer = {}
        self.map_is_threat_safe = True
        self._hot_fix_check_wait = Timer(6)
        self.config = SimpleNamespace(BUTTON_OFFSET=30, Campaign_Event='campaign_main')
        self.device = ClickContractDevice(dialog_frame, on_click=self.leave)
        self.device.screenshot = self.screenshot

    def leave(self):
        """The game answers the click that really reaches it, and swallows the others.

        While the dialog is up the touch of the reward panel never reaches the game, which is
        what the archived log shows: eleven clicks on the panel and no change of the picture.
        """
        name = self.device.click_record[-1]
        if name == str(ANDROID_NO_RESPOND_DARK):
            self.device.image = self.frames[1]
        elif name == str(AUTO_SEARCH_REWARD) and self.answer:
            self.device.image = self.frames[2]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no exit after {self.limit} screenshots')
        return self.device.image


class PagePollApp:
    """The UI instance `UI.ui_get_current_page()` needs, with the real module code bound to it."""

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

    def ui_additional(self, get_ship=True):
        return False

    def handle_login_page(self, interval=3):
        return False


class NoRespondFrameTest(unittest.TestCase):
    """What the archived frames of the incident really hold."""

    def test_the_crash_frame_holds_the_dialog(self):
        frame = image(NO_RESPOND)
        self.assertTrue(ANDROID_NO_RESPOND_DARK.match(frame, offset=(30, 30)))
        # The asset of the login loop is the same icon in the light theme of another emulator, so
        # it cannot see this dialog: that is why a running task had no handler for it at all.
        self.assertFalse(ANDROID_NO_RESPOND.match(frame, offset=(30, 30)))

    def test_the_dialog_swallows_the_click_of_the_panel(self):
        """The panel is recognized and localized, and the click still cannot reach it."""
        frame = image(NO_RESPOND)
        self.assertTrue(AUTO_SEARCH_REWARD.match(frame, offset=(50, 50)))
        # The dialog covers the middle of the display and the panel's button is below it, inside
        # the dimmed area of the same modal window.
        self.assertGreater(AUTO_SEARCH_REWARD.button[3], DIALOG_BOX[3])
        # The dismiss click of the handler is inside the 等待 row of the dialog.
        button = ANDROID_NO_RESPOND_DARK.button
        self.assertGreaterEqual(button[0], WAIT_ROW[0])
        self.assertGreaterEqual(button[1], WAIT_ROW[1])
        self.assertLessEqual(button[2], WAIT_ROW[2])
        self.assertLessEqual(button[3], WAIT_ROW[3])

    def test_the_panel_frame_without_the_dialog_is_left_alone(self):
        frame = image(PANEL)
        self.assertTrue(AUTO_SEARCH_REWARD.match(frame, offset=(50, 50)))
        self.assertFalse(ANDROID_NO_RESPOND.match(frame, offset=(30, 30)))
        self.assertFalse(ANDROID_NO_RESPOND_DARK.match(frame, offset=(30, 30)))


class NoRespondHandlerTest(unittest.TestCase):
    """The handler both the login loop and the game loops use."""

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_dialog_is_dismissed_with_its_wait_row(self):
        app = FakeApp(image(NO_RESPOND))
        self.assertTrue(handle_android_no_respond(app))
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], WAIT_ROW)
        self.assert_in_area(app.device.clicked[0], ANDROID_NO_RESPOND_DARK.button)
        # Counted once, by hand, and the click itself does not count again.
        self.assertEqual(list(app.device.click_record), [str(ANDROID_NO_RESPOND_DARK)])

    def test_a_frame_without_the_dialog_is_left_alone(self):
        for name in (PANEL, 'map'):
            with self.subTest(frame=name):
                app = FakeApp(image(name))
                self.assertFalse(handle_android_no_respond(app))
                self.assertEqual(app.device.clicked, [])
                self.assertEqual(list(app.device.click_record), [])

    def test_the_interval_prevents_a_burst(self):
        app = FakeApp(image(NO_RESPOND))
        self.assertTrue(handle_android_no_respond(app))
        self.assertFalse(handle_android_no_respond(app))
        self.assertEqual(len(app.device.clicked), 1)

    def test_a_dialog_that_cannot_be_dismissed_ends_with_the_click_guard(self):
        """Eleven clicks, then the twelve click guard of the device, as in the live log.

        The guard clears the click record before it raises, which is what the `History click:` line
        of the live log shows, so the clicks that were sent are asserted instead.
        """
        app = FakeApp(image(NO_RESPOND))
        with patch('module.device.device.show_function_call', lambda: None):
            with self.assertRaises(GameTooManyClickError):
                for _ in range(12):
                    handle_android_no_respond(app, interval=0)
        self.assertEqual(len(app.device.clicked), 11)
        for point in app.device.clicked:
            self.assert_in_area(point, WAIT_ROW)
        self.assertEqual(list(app.device.click_record), [])


class QuitLoopTest(unittest.TestCase):
    """The reward loop that ended the live task, on the archived frames."""

    def app(self, answer=True, limit=4000):
        return QuitLoopApp(image(NO_RESPOND), image(PANEL), image('map'), answer=answer, limit=limit)

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_reward_loop_dismisses_the_dialog_before_the_panel(self):
        app = self.app()
        app.os_auto_search_quit()
        self.assertEqual(list(app.device.click_record),
                         [str(ANDROID_NO_RESPOND_DARK), str(AUTO_SEARCH_REWARD)])
        self.assert_in_area(app.device.clicked[0], WAIT_ROW)
        self.assert_in_area(app.device.clicked[1], AUTO_SEARCH_REWARD.button)
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_handler_the_loop_spends_its_clicks_on_the_panel(self):
        """The pre-fix behaviour of the same frames, for the record.

        The dialog swallows the panel click, so the loop keeps clicking AUTO_SEARCH_REWARD every
        two seconds until the twelve click guard of the device ends the task, which is the crash of
        the live log.  The clock is a stand-in so the twenty two seconds of the live run do not
        have to be spent here.
        """
        app = self.app(answer=False, limit=200)
        with patch('module.os_handler.map_event.handle_android_no_respond', lambda app: False):
            with patch('module.base.timer.time', FakeClock()):
                with patch('module.device.device.show_function_call', lambda: None):
                    with self.assertRaises(GameTooManyClickError):
                        app.os_auto_search_quit()
        self.assertEqual(len(app.device.clicked), 11)
        for point in app.device.clicked:
            self.assert_in_area(point, AUTO_SEARCH_REWARD.button)
        self.assertLess(app.screenshots, app.limit)

    def test_the_map_frame_is_the_end_condition(self):
        frame = image('map')
        self.assertTrue(IN_MAP.match_luma(frame, offset=(200, 5)))
        self.assertFalse(ANDROID_NO_RESPOND_DARK.match(frame, offset=(30, 30)))
        self.assertFalse(AUTO_SEARCH_REWARD.match(frame, offset=(50, 50)))

    def test_map_event_handles_the_dialog_first(self):
        """The other operation siren loops reach the dialog through handle_map_event()."""
        frame = image(NO_RESPOND)
        app = QuitLoopApp(frame, image(PANEL), image('map'))
        self.assertEqual(app.handle_map_event(), 'android_no_respond')
        self.assertEqual(list(app.device.click_record), [str(ANDROID_NO_RESPOND_DARK)])
        for button, offset in ((GLOBE_GOTO_MAP, (20, 20)), (STORAGE_CHECK, (20, 20))):
            with self.subTest(button=str(button)):
                self.assertFalse(button.match(frame, offset=offset))
        self.assertFalse(MAP_GOTO_GLOBE_FOG.match_template_color(frame, offset=(5, 5)))


class NoRespondLoginDevice(LoginDevice):
    """`LoginDevice` plus the click guard `handle_android_no_respond()` asks for by hand.

    The stand-in of the login tests never needed it: the light asset of that loop does not match
    the dialog of this emulator, so the branch that calls it could not run there.  The screenshot
    budget is what turns a login loop that cannot leave the dialog into a failure instead of a
    loop that never ends.
    """

    click_record_check = Device.click_record_check

    def __init__(self, *args, limit=50, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = limit
        self.screenshots = 0

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'the login loop did not advance after {self.limit} screenshots')
        return super().screenshot()


class LoginLoopTest(unittest.TestCase):
    """The login loop, the other caller of the handler, on the same archived dialog.

    `_handle_app_login()` was the only place that answered the dialog, and only with the light
    asset, so it could not answer this one either: the same frames of the live dump are used here.
    """

    def setUp(self):
        self.home = load_frame(HOME_FRAME)
        patcher = patch('module.handler.login.Timer', FakeTimer)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_the_login_loop_dismisses_the_dark_dialog(self):
        device = NoRespondLoginDevice(image(NO_RESPOND), self.home, clicks_until_home=1)
        runner = FakeLogin(device)
        self.assertTrue(runner._handle_app_login())
        self.assertEqual(list(device.click_record), [str(ANDROID_NO_RESPOND_DARK)])
        self.assertEqual(len(device.clicked), 1)
        x, y = device.clicked[0]
        self.assertTrue(WAIT_ROW[0] <= x <= WAIT_ROW[2], f'x of {device.clicked[0]} is outside {WAIT_ROW}')
        self.assertTrue(WAIT_ROW[1] <= y <= WAIT_ROW[3], f'y of {device.clicked[0]} is outside {WAIT_ROW}')


class PagePollTest(unittest.TestCase):
    """The page poll of a scheduler that meets the dialog."""

    def test_the_poll_dismisses_the_dialog_instead_of_reporting_the_page(self):
        app = PagePollApp([NO_RESPOND, NO_RESPOND, NO_RESPOND, 'map'], hold=3)
        page = app.ui_get_current_page()
        self.assertIs(page, page_os)
        self.assertEqual(list(app.device.click_record), [str(ANDROID_NO_RESPOND_DARK)])
        self.assertLess(app.screenshots, app.limit)

    def test_without_the_handler_the_poll_reports_the_page_as_unknown(self):
        app = PagePollApp([NO_RESPOND], hold=1, limit=2000)
        with patch('module.ui.ui.handle_android_no_respond', lambda app: False):
            with self.assertRaises(GamePageUnknownError):
                app.ui_get_current_page()
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
