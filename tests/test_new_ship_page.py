import collections
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat import new_ship_page
from module.combat.auto_search_combat import AutoSearchCombat
from module.combat.new_ship_page import (CONFIRM_BUTTON_COLOR, CONFIRM_SEARCH_AREA, confirm_ocr,
                                         find_confirm_button_area, handle_new_ship_page, is_confirm_label,
                                         match_new_ship_confirm)
from module.device.control import Control

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/new_ship_page'

# Confirm button of the `NEW SHIP ACQUIRED` page, the same area on every archived frame.
CONFIRM_AREA = (993, 602, 1168, 661)


def clear():
    new_ship_page.confirm_click_timer.reset()
    new_ship_page.confirm_click_timer._start = 0
    new_ship_page.confirm_attempt = 0
    new_ship_page.confirm_clicked_at = 0.


@contextmanager
def fresh_click_state():
    """Reset the module level click state of the handler, and restore it after."""
    clear()
    try:
        yield
    finally:
        clear()


class LoopLimitReached(Exception):
    """Raised by the stand-in device when a loop does not advance on its own."""


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


class NewShipPageFrameTest(unittest.TestCase):
    """The `NEW SHIP ACQUIRED` page that blocked GemsFarming on 2026-09-21.

    Live log/error/1789931082750: GemsFarming on campaign 2-4 dropped 大斗犬 for the first time at
    03:01:42, so the game left the ship obtained screen for the ship detail page of that ship, with
    the `NEW SHIP ACQUIRED` banner, the 档案 panel and one blue 确定 button.  Nothing that
    `AutoSearchCombat.auto_search_combat_status()` polls matches that page, so the loop ended in the
    stuck check of the device: `GameStuckError: Wait too long` at 03:04:42.

    `new-ship-0304.png` is the archived frame of this dump, `new-ship-0730.png` the frame of
    log/error/1785374923997 (2026-07-30, 列克星敦), the oldest of the ten dumps that end on this page
    with the same wait list, all of them after `Click @ GET_SHIP`.
    """

    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def app(self, name):
        return SimpleNamespace(device=ClickContractDevice(self.image(name)))

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_confirm_button_is_localized_on_the_archived_frames(self):
        for name in ('new-ship-0304', 'new-ship-0730'):
            with self.subTest(name=name):
                button = match_new_ship_confirm(self.image(name))
                self.assertIsNotNone(button)
                self.assertEqual(str(button), 'NEW_SHIP_CONFIRM')
                # The recognition is the blue body of the button plus its label, and the
                # localization is the same measurement, not a fixed coordinate.
                self.assertEqual(tuple(button.area), CONFIRM_AREA)
                self.assertEqual(tuple(button.button), CONFIRM_AREA)
                self.assertEqual(tuple(button.color), CONFIRM_BUTTON_COLOR)
                self.assert_in_area(CONFIRM_AREA[:2], CONFIRM_SEARCH_AREA)

    def test_the_label_reads_back_from_the_archived_frame(self):
        """The recognition path runs the real OCR of the localized button."""
        image = self.image('new-ship-0304')
        confirm_ocr.buttons = find_confirm_button_area(image)
        label = confirm_ocr.ocr(image)
        self.assertTrue(is_confirm_label(label), f'label {label!r} is not a confirm label')

    def test_the_label_survives_dropped_wrong_and_residual_characters(self):
        for label in ('确定', '確定', '確認', '确认', '碓定', '确', '定', '确定定', '确定。', ' 确定 '):
            with self.subTest(label=label):
                self.assertTrue(is_confirm_label(label))

    def test_another_label_is_not_a_confirm_label(self):
        # Live frame 2026-07-27: the blue button of the META beacon page reads 领励, one character
        # of 领取奖励 was dropped by the OCR.  A label comparison that only counts characters would
        # take it for a confirm button.
        for label in ('领励', '领取奖励', '取消', '出击', '再次前往', '', '1', 'ARCHIVES'):
            with self.subTest(label=label):
                self.assertFalse(is_confirm_label(label))

    def test_another_blue_button_is_rejected(self):
        image = self.image('other-confirm-0727')
        # The blue body of the button is found, the label of that page is not a confirm label.
        self.assertIsNotNone(find_confirm_button_area(image))
        self.assertIsNone(match_new_ship_confirm(image))

    def test_a_map_frame_has_no_confirm_button(self):
        image = self.image('campaign-map')
        self.assertIsNone(find_confirm_button_area(image))
        self.assertIsNone(match_new_ship_confirm(image))

    def test_the_page_is_clicked_once_and_then_left_alone(self):
        app = self.app('new-ship-0304')
        with fresh_click_state():
            self.assertTrue(handle_new_ship_page(app))
            self.assertEqual(len(app.device.clicked), 1)
            self.assert_in_area(app.device.clicked[0], CONFIRM_AREA)
            # The click timer prevents a burst of clicks while the page switches.
            self.assertFalse(handle_new_ship_page(app))
            self.assertEqual(len(app.device.clicked), 1)

    def test_the_click_target_is_the_button_of_the_page(self):
        """The handler hands the Button to the device, and the click record sees it.

        `Device.click()` reads `button.button` and registers the button, so a coordinate would both
        crash here and leave the too-many-click guard of the device without a name to count.
        """
        app = self.app('new-ship-0304')
        with fresh_click_state():
            self.assertTrue(handle_new_ship_page(app))
        self.assertEqual(list(app.device.click_record), ['NEW_SHIP_CONFIRM'])

    def test_a_still_blocked_page_is_retried_and_then_left_alone(self):
        app = self.app('new-ship-0304')
        with fresh_click_state():
            for _ in range(new_ship_page.CONFIRM_MAX_ATTEMPT):
                new_ship_page.confirm_click_timer.reset()
                new_ship_page.confirm_click_timer._start = 0
                self.assertTrue(handle_new_ship_page(app))
            self.assertEqual(len(app.device.clicked), new_ship_page.CONFIRM_MAX_ATTEMPT)
            for point in app.device.clicked:
                self.assert_in_area(point, CONFIRM_AREA)
            # After the attempts are spent the page is reported instead of being clicked on.
            new_ship_page.confirm_click_timer.reset()
            new_ship_page.confirm_click_timer._start = 0
            self.assertFalse(handle_new_ship_page(app))
            self.assertEqual(len(app.device.clicked), new_ship_page.CONFIRM_MAX_ATTEMPT)

    def test_a_new_page_gets_its_own_attempts(self):
        app = self.app('new-ship-0304')
        with fresh_click_state():
            new_ship_page.confirm_attempt = new_ship_page.CONFIRM_MAX_ATTEMPT
            # No click for longer than the stale timeout: this page is a new battle.
            new_ship_page.confirm_clicked_at = 0.
            self.assertTrue(handle_new_ship_page(app))
            self.assertEqual(len(app.device.clicked), 1)

    def test_a_page_of_another_screen_is_not_clicked(self):
        other = self.app('other-confirm-0727')
        campaign_map = self.app('campaign-map')
        with fresh_click_state():
            self.assertFalse(handle_new_ship_page(other))
            self.assertFalse(handle_new_ship_page(campaign_map))
        self.assertEqual(other.device.clicked, [])
        self.assertEqual(campaign_map.device.clicked, [])


class StatusLoopDevice(ClickContractDevice):
    """The device `auto_search_combat_status()` needs.

    It clicks through the real `Control.click()`, serves the archived page, moves to the map when a
    click arrives, and stops the loop after `limit` screenshots so a loop that cannot advance fails
    the test instead of spinning forever.
    """

    def __init__(self, page_frame, map_frame, limit):
        self.frames = (page_frame, map_frame)
        self.limit = limit
        self.screenshots = 0
        super().__init__(page_frame, on_click=self.leave_new_ship_page)

    def leave_new_ship_page(self):
        # The game leaves the new ship page for the map once the confirm button is clicked.
        self.image = self.frames[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.limit:
            raise LoopLimitReached(f'no exit after {self.limit} screenshots')
        return self.image


class StatusLoopApp:
    """The Alas instance `auto_search_combat_status()` needs, with the real loop bound to it.

    Only the device is a stand-in, and every handler of the loop except the new ship page is
    stubbed out, so the loop can only advance through the new ship page handler.
    """

    auto_search_combat_status = AutoSearchCombat.auto_search_combat_status
    loop = ModuleBase.loop
    _auto_search_status_confirm = False

    def __init__(self, page_frame, map_frame, limit=5000):
        self.device = StatusLoopDevice(page_frame, map_frame, limit)

    def is_auto_search_running(self):
        # The click leaves the page for the map, where auto search keeps running.
        return self.device.image is self.device.frames[1]

    def __getattr__(self, item):
        return lambda *args, **kwargs: False


class AutoSearchCombatStatusTest(unittest.TestCase):
    """The loop of the crash: it has to end on the archived page instead of timing out."""

    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_the_status_loop_ends_on_the_archived_frame(self):
        app = StatusLoopApp(self.image('new-ship-0304'), self.image('campaign-map'))
        with fresh_click_state():
            self.assertFalse(app.auto_search_combat_status())
        self.assertEqual(len(app.device.clicked), 1)
        self.assert_in_area(app.device.clicked[0], CONFIRM_AREA)
        self.assertLess(app.device.screenshots, app.device.limit)

    def test_without_the_handler_the_status_loop_never_ends(self):
        """The pre-fix behaviour of the same frame, for the record."""
        app = StatusLoopApp(self.image('new-ship-0304'), self.image('campaign-map'), limit=50)
        with fresh_click_state(), patch('module.combat.auto_search_combat.handle_new_ship_page',
                                        lambda app: False):
            with self.assertRaises(LoopLimitReached):
                app.auto_search_combat_status()
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
