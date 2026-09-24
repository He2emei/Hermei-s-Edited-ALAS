"""Regression tests for the login title screen that no click can pass.

Live incidents:

- 2026-09-24 10:05:33, dump log/error/1790215533063, `Restart` task of the `alas` profile:
  `GameTooManyClickError: Too many click for a button: LOGIN_CHECK`.  The CN channel
  client (`com.bilibili.azurlane`) came up on its title screen while the game server was
  under maintenance, so `_handle_app_login()` could only click LOGIN_CHECK.  Its 180s
  patience was supposed to hand that stall to the scheduler's server checker, but the
  12-click guard of `Device.click_record_check()` ended the task after ~56s (measured
  below with the real timers), so the patience was unreachable.  Three failed `Restart`
  tasks then took the whole ALAS process down.  The same signature has 235 archived
  dumps.

- 2026-09-24 15:57:05, dump log/error/1790236625054, `Commission` task:
  `GameTooManyClickError: Too many click between 2 buttons: LOGIN_CHECK, GET_SHIP`.
  Here the entry point was the page poll (`UI.ui_get_current_page()` ->
  `ui_additional()`), and the title screen's white artwork passed the colour-only GET_SHIP
  check of `ui_page_main_popups()`: the asset area is a 6x20 white strip and
  `appear_then_click()` checks it with `threshold=30`, while the tolerance of that area on
  the archived frame is 15.25.  The click went to the main page's get-ship box, which on
  that page is the legal notice band, and together with the LOGIN_CHECK clicks it filled
  the 2-button guard after ~27s.  Both profiles repeated this from 12:13 to 15:57
  (64 dumps with that signature).
"""
import collections
import unittest
from pathlib import Path
from time import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import cv2

from module.base.timer import Timer
from module.combat.assets import GET_SHIP
from module.device.control import Control
from module.exception import GamePageUnknownError, GameTooManyClickError
from module.handler.assets import LOGIN_CHECK
from module.handler.login import LoginHandler
from module.ui.page import page_main
from module.ui.ui import UI

FIXTURES = Path(__file__).parent / 'fixtures' / 'login_title_stall'
TITLE_FRAMES = ('login-title-1005', 'login-title-1007', 'login-title-1557')
# log/error/1769416959539 (2026-01-26 16:42:38), a frame the real page_main check passes.
HOME_FRAME = FIXTURES / 'page-main-0126.png'


def load_frame(path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None, f'cannot read {path}'
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class FakeTimer:
    """`module.base.timer.Timer` whose clock the test drives.

    `_handle_app_login()` builds its confirm and orientation timers itself, so patching
    the class is the only way to reach them.  Every timer but the login page patience
    fires on its first check, which is what the real timers do after the ~1s of a real
    screenshot.  The patience is a `UI` class attribute and a real timer, the tests drive
    it directly.
    """

    def __init__(self, limit, count=0):
        self.limit = limit
        self.count = count
        self.elapsed = limit
        self._started = False
        self._cleared = False
        self.running = True

    def start(self):
        self._started = True
        self._cleared = False
        return self

    def reset(self):
        # The clock is virtual: a reset marks the timer as started again, it does not make
        # the stand-in wait, so `reached()` keeps answering from `elapsed`.
        self._started = True
        self._cleared = False
        return self

    def clear(self):
        self._started = False
        self._cleared = True
        self.elapsed = 0.0
        return self

    def started(self):
        return self._started

    def reached(self):
        # `count` is ignored on purpose: the loop's confirm timer is
        # `Timer(1.5, count=4)` and a stand-in that honours the access count stops firing,
        # which would leave the loop running until the click guard instead of returning.
        if self._cleared or not self._started or not self.running:
            return False
        return self.elapsed >= self.limit

    def current_time(self):
        return self.elapsed


class LoginDevice:
    """A device stub that clicks through the real `Control.click()`.

    `Control.click()` takes a Button, reads `button.button` and adds the button to the
    click record of the device; the archived title screen needs the real click record,
    because the incident *is* the 12-click guard of that record.
    """

    click = Control.click

    def __init__(self, title_frame, home_frame, clicks_until_home=None, click_limit=12):
        self.title_frame = title_frame
        self.home_frame = home_frame
        self.clicks_until_home = clicks_until_home
        self.click_limit = click_limit
        self.image = title_frame
        self.clicked = []
        self.click_record = collections.deque(maxlen=15)
        self.stuck = set()
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB', BUTTON_OFFSET=30)

    @property
    def click_methods(self):
        return {'ADB': self.click_adb}

    def screenshot(self):
        if self.clicks_until_home is not None and len(self.clicked) >= self.clicks_until_home:
            self.image = self.home_frame
        else:
            self.image = self.title_frame
        return self.image

    def click_adb(self, x, y):
        self.clicked.append((x, y))

    def handle_control_check(self, button):
        # Device.handle_control_check(): clear the stuck record, record the click, check it.
        self.stuck.clear()
        self.click_record.append(str(button))
        count = collections.Counter(self.click_record).most_common(1)[0]
        if count[1] >= self.click_limit:
            self.click_record.clear()
            raise GameTooManyClickError(f'Too many click for a button: {count[0]}')

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        removed = 0
        while str(button) in self.click_record:
            self.click_record.remove(str(button))
            removed += 1
        return removed

    def stuck_record_add(self, button):
        self.stuck.add(str(button))

    def stuck_record_clear(self):
        self.stuck.clear()

    def get_orientation(self):
        return 1

    def app_is_running(self):
        return True

    def sleep(self, _seconds):
        return None


class FakeUI(UI):
    """The real `ui_additional()` of the page poll against the archived frames.

    Nothing is stubbed here on purpose: the reported crash happened inside
    `ui_additional()` -> `ui_page_main_popups()` -> `appear_then_click(GET_SHIP)`.
    """

    def __init__(self, device):
        self.device = device
        self.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=30,
                                      Emulator_ScreenshotMethod='nemu_ipc',
                                      Emulator_ControlMethod='MaaTouch')
        self.interval_timer = {}
        self.ui_current = None


class FakeLogin(LoginHandler):
    """The real `_handle_app_login()` loop against the archived frames."""

    def __init__(self, device):
        self.device = device
        self.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=30,
                                      Emulator_ScreenshotMethod='nemu_ipc',
                                      Emulator_ControlMethod='MaaTouch')
        self.interval_timer = {}

    def ui_page_main_popups(self, *args, **kwargs):
        return False

    def handle_popup_confirm(self, *args, **kwargs):
        return False

    def handle_urgent_commission(self):
        return False

    def handle_cn_user_agreement(self):
        return False


class LoginPagePatienceTest(unittest.TestCase):
    def setUp(self):
        self.home = load_frame(HOME_FRAME)
        self.title = load_frame(FIXTURES / 'login-title-1005.png')
        self.title_1557 = load_frame(FIXTURES / 'login-title-1557.png')
        self.patience = UI._login_page_timer
        self.patience.clear()
        patcher = patch('module.handler.login.Timer', FakeTimer)
        self.addCleanup(patcher.stop)
        patcher.start()

    def tearDown(self):
        self.patience.clear()

    def expire_patience(self):
        """Pretend the login page has already been on screen for the patience."""
        self.patience._start = time() - self.patience.limit - 1
        self.patience._access = 100

    def test_title_screen_past_the_patience_is_a_game_page_unknown(self):
        """The archived title screen: clicks, then the maintenance handover.

        The patience starts one second before its limit, so the loop clicks the page (the
        click interval is 5s) and the handover follows as soon as the patience runs out.
        """
        self.patience._start = time() - self.patience.limit + 1
        self.patience._access = 100
        device = LoginDevice(self.title, self.home)
        runner = FakeLogin(device)
        with self.assertRaises(GamePageUnknownError):
            runner._handle_app_login()
        self.assertGreater(len(device.clicked), 0, 'the loop did not try the title screen')
        self.assertLess(len(device.clicked), device.click_limit,
                        'the 12-click guard was reached before the patience handover')
        self.assertEqual(device.click_record, collections.deque(maxlen=15),
                         'the stalled clicks were left in the click record')
        for point in device.clicked:
            self.assertTrue(LOGIN_CHECK.button[0] <= point[0] <= LOGIN_CHECK.button[2])
            self.assertTrue(LOGIN_CHECK.button[1] <= point[1] <= LOGIN_CHECK.button[3])

    def test_the_click_guard_cannot_end_a_stalled_login_page(self):
        """The login page owns its clicks, its patience is what ends a stall.

        `_handle_app_login()` clicks the login page every 5s, so the 12-click guard of
        `Device.click_record_check()` ends the task after 12 clicks (~56s against the
        archived frames, measured with the real timers).  A patience of 180s could never
        be reached that way, which is why the clicks of this page are not counted by the
        guard.  The stub device below raises after 3 recorded clicks, and the loop clicks
        at `interval=0` so the test does not have to wait out the real interval.
        """
        device = LoginDevice(self.title, self.home, click_limit=3)
        ui = FakeLogin(device)
        for _ in range(20):
            # A cleared interval timer clicks on every call; this test is about the click
            # guard, not about the interval between two clicks.
            ui.interval_clear(LOGIN_CHECK)
            self.assertTrue(ui.handle_login_page(interval=0))
        self.assertGreaterEqual(len(device.clicked), 20,
                                'the login page was not clicked while it was stalled')
        self.assertEqual(device.click_record, collections.deque(maxlen=15),
                         'the clicks of the login page were counted by the click guard')

    def test_normal_login_returns_after_the_first_click(self):
        device = LoginDevice(self.title, self.home, clicks_until_home=1)
        runner = FakeLogin(device)
        self.assertTrue(runner._handle_app_login())
        self.assertEqual(len(device.clicked), 1)
        self.assertEqual(str(LOGIN_CHECK), 'LOGIN_CHECK')

    def test_page_poll_does_not_click_get_ship_on_the_title_screen(self):
        """The reported crash: the page poll must not handle page_main popups here.

        Dump log/error/1790236625054, 2026-09-24 15:57:05: the GET_SHIP area is white
        enough for the colour-only check of `appear_then_click()` (threshold=30), so the
        page poll clicked the get-ship box of the main page, which on the title screen is
        the legal notice band, and the interleaved LOGIN_CHECK clicks filled the 2-button
        guard after ~27s.
        """
        device = LoginDevice(self.title_1557, self.home)
        ui = FakeUI(device)
        ui.ui_additional()
        self.assertTrue(device.clicked, 'the page poll did not click anything at all')
        for x, y in device.clicked:
            self.assertTrue(LOGIN_CHECK.button[0] <= x <= LOGIN_CHECK.button[2],
                            f'click {(x, y)} is outside the login page button')
            self.assertTrue(LOGIN_CHECK.button[1] <= y <= LOGIN_CHECK.button[3],
                            f'click {(x, y)} is outside the login page button')
            self.assertFalse(GET_SHIP.button[0] <= x <= GET_SHIP.button[2]
                             and GET_SHIP.button[1] <= y <= GET_SHIP.button[3],
                             f'click {(x, y)} is the main page get-ship box')

    def test_page_poll_hands_a_stalled_login_page_over(self):
        """The page poll gives the login page the same patience as the app login."""
        self.expire_patience()
        device = LoginDevice(self.title_1557, self.home)
        ui = FakeUI(device)
        with self.assertRaises(GamePageUnknownError):
            ui.ui_additional()
        self.assertEqual(device.click_record, collections.deque(maxlen=15),
                         'the stalled clicks were left in the click record')

    def test_archived_frames_are_the_same_title_screen(self):
        for name in TITLE_FRAMES:
            with self.subTest(name=name):
                image = load_frame(FIXTURES / f'{name}.png')
                self.assertTrue(LOGIN_CHECK.match_template_color(image, offset=(30, 30)))
                self.assertFalse(page_main.check_button.match(image, offset=(30, 30)),
                                 'the home page check must not match the title screen')

    def test_the_clicked_box_is_not_a_button_on_the_archived_frames(self):
        """Recognition is the CRIWARE mark, the click box is artwork - not a mis-read."""
        image = load_frame(FIXTURES / 'login-title-1005.png')
        LOGIN_CHECK.ensure_template()
        self.assertEqual(tuple(LOGIN_CHECK.area), (1214, 653, 1268, 709))
        self.assertEqual(tuple(LOGIN_CHECK.button), (416, 294, 534, 400))
        self.assertEqual(tuple(LOGIN_CHECK.button), tuple(LOGIN_CHECK._button),
                         'the asset was offset, the click box is no longer the asset box')
        # The CRIWARE mark matches the asset exactly, the click box is plain artwork.
        area = image[653:709, 1214:1268]
        box = image[294:400, 416:534]
        self.assertLess(float(np.abs(area.mean(axis=(0, 1)) - np.array(LOGIN_CHECK.color)).max()), 1.0)
        self.assertGreater(float(np.abs(box.mean(axis=(0, 1)) - np.array(LOGIN_CHECK.color)).max()), 30.0)

    def test_get_ship_area_passes_the_colour_only_check_on_the_title_screen(self):
        """The root cause of the 15:57 crash, measured on the archived frame.

        `ui_page_main_popups()` calls `appear_then_click(GET_SHIP, interval=5)` without an
        offset, which is the colour-only `Button.appear_on()` path, and
        `appear_then_click()` passes `threshold=30`.  The tolerance of the asset area on
        the title screen is 15.25, so the check passes on a page that has no such button.
        """
        image = load_frame(FIXTURES / 'login-title-1557.png')
        area = image[GET_SHIP.area[1]:GET_SHIP.area[3], GET_SHIP.area[0]:GET_SHIP.area[2]]
        tolerance = float(np.abs(area.mean(axis=(0, 1)) - np.array(GET_SHIP.color)).max())
        self.assertTrue(GET_SHIP.appear_on(image, threshold=30),
                        'the frame no longer reproduces the colour-only false positive')
        self.assertFalse(GET_SHIP.appear_on(image, threshold=10))
        self.assertLess(tolerance, 30)
        self.assertFalse(GET_SHIP.match_template_color(image, offset=(30, 30)),
                         'the template check does not match, only the colour check does')


if __name__ == '__main__':
    unittest.main()
