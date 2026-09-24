"""Regression tests for the login title screen that no click can pass.

Live incident: 2026-09-24 10:05:33, dump log/error/1790215533063, `Restart` task of the
`alas` profile, frame tests/fixtures/login_title_stall/login-title-1005.png.  The CN
channel client (`com.bilibili.azurlane`) came up on its title screen - night sky, two
character illustrations, 服务器 [ 杜立特空袭 点击更换 ], 触摸屏幕执行权限认证 PRESS TO
START - and the game server was under maintenance (`state: 1` from the server checker
API for that server name at that time).  `_handle_app_login()` clicked LOGIN_CHECK every
5s; the asset matches the CRIWARE mark in the bottom right corner of that page while its
button box (416, 294, 534, 400) is the character artwork in the middle of the screen, so
the delivered clicks could not move the game on.  The 12-click guard of
`Device.click_record_check()` then ended the task with `GameTooManyClickError`, the
scheduler ran `Restart` three times, and `Task `Restart` failed 3 or more times` took the
whole ALAS process down at 10:08:32 - the outage of 2025-12-04 repeated.  The same
signature has 193 archived dumps, 163 of them in the 10 o'clock maintenance hour.
"""
import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import cv2

from module.base.timer import Timer
from module.device.control import Control
from module.exception import GamePageUnknownError, GameTooManyClickError
from module.handler.assets import LOGIN_CHECK
from module.handler.login import LoginHandler
from module.ui.page import page_main

FIXTURES = Path(__file__).parent / 'fixtures' / 'login_title_stall'
TITLE_FRAMES = ('login-title-1005', 'login-title-1007')
# log/error/1769416959539 (2026-01-26 16:42:38), a frame the real page_main check passes.
HOME_FRAME = FIXTURES / 'page-main-0126.png'


def load_frame(path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None, f'cannot read {path}'
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class FakeTimer:
    """`module.base.timer.Timer` whose clock the test drives.

    `_handle_app_login()` builds its timers itself, so patching the class is the only way
    to reach them.  Every timer but the login page timer fires on its first check, which
    is what the real timers do after the ~1s of a real screenshot.
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
        self.config = SimpleNamespace(Emulator_ControlMethod='ADB')

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


class FakeLogin(LoginHandler):
    """The real `_handle_app_login()` loop against the archived frames.

    `patience_running=False` keeps the login page patience from being reached, which is
    the stall the fix has to hand over to the scheduler; the default reaches it at once.
    """

    patience_running = True

    def __init__(self, device):
        self.device = device
        self.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=30,
                                      Emulator_ScreenshotMethod='nemu_ipc',
                                      Emulator_ControlMethod='MaaTouch')
        self.interval_timer = {}
        # The loop clicks LOGIN_CHECK at `interval=5`, and that interval timer is a real
        # `module.base.timer.Timer` owned by Base.appear(), which the patch above cannot
        # reach.  Starting it in the past makes the first click immediate; Base.appear()
        # resets it after every match, so a stalled loop still spends the real interval
        # between clicks.  The limit has to be the loop's own interval, otherwise
        # Base.appear() replaces the timer with a fresh one.
        LOGIN_CHECK.clear_offset()
        timer = self.interval_timer[LOGIN_CHECK.name] = Timer(5)
        timer._start = -1e9
        timer._access = 1

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
        self.timers = []
        patcher = patch('module.handler.login.Timer', self.make_timer)
        self.addCleanup(patcher.stop)
        patcher.start()

    def make_timer(self, limit, count=0):
        timer = FakeTimer(limit, count=count)
        if limit == LoginHandler.login_page_patience:
            timer.running = FakeLogin.patience_running
        self.timers.append(timer)
        return timer

    def test_title_screen_past_the_patience_is_a_game_page_unknown(self):
        """The archived title screen: a few clicks, then the maintenance handover."""
        FakeLogin.patience_running = True
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

    def test_short_stall_still_clicks_until_the_click_guard(self):
        """A stall inside the patience keeps the existing click guard behaviour.

        `patience_running=False` is the stall that has not lasted long enough yet, so the
        loop has to keep clicking LOGIN_CHECK until `Device.click_record_check()` ends the
        task exactly as it did before this fix.
        """
        FakeLogin.patience_running = False
        device = LoginDevice(self.title, self.home, click_limit=3)
        runner = FakeLogin(device)
        with self.assertRaises(GameTooManyClickError) as caught:
            runner._handle_app_login()
        self.assertIn('LOGIN_CHECK', str(caught.exception))
        self.assertGreaterEqual(len(device.clicked), 1)
        self.assertLessEqual(len(device.clicked), device.click_limit,
                             'the loop kept clicking past the click guard')

    def test_normal_login_returns_after_the_first_click(self):
        FakeLogin.patience_running = False
        device = LoginDevice(self.title, self.home, clicks_until_home=1)
        runner = FakeLogin(device)
        self.assertTrue(runner._handle_app_login())
        self.assertEqual(len(device.clicked), 1)
        self.assertEqual(str(LOGIN_CHECK), 'LOGIN_CHECK')

    def test_patience_outlasts_the_click_guard_window(self):
        """The handover has to happen before the 12-click guard can end the task.

        The loop clicks LOGIN_CHECK at a 5s interval, so the guard of
        `Device.click_record_check()` is reached after about 55s.  A patience shorter
        than that would hand the stall over only after the task already died.
        """
        self.assertGreater(LoginHandler.login_page_patience, 12 * 5)

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


if __name__ == '__main__':
    unittest.main()
