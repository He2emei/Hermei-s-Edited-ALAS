import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.device.control import Control
from module.device.device import Device
from module.exception import GamePageUnknownError, RequestHumanTakeover
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.os_handler.assets import STRATEGIC_SEARCH_POPUP_CHECK
from module.ui.page import page_os
from module.ui.ui import UI


ROOT = Path(__file__).parents[1]
POPUP_FRAME = np.asarray(Image.open(
    ROOT / 'tests/fixtures/strategic_search/settings-popup-20261014.png'
).convert('RGB'))
MAP_FRAME = np.asarray(Image.open(
    ROOT / 'tests/fixtures/battle_result/os-map-cleared.png'
).convert('RGB'))


class FakeClock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        self.now += 0.5
        return self.now


class ClickContractDevice:
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

    def stuck_record_add(self, button):
        pass

    def stuck_record_clear(self):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def screenshot(self):
        return self.image

    @property
    def has_cached_image(self):
        return False

    def app_is_running(self):
        return True

    def get_orientation(self):
        return 1

    def uninstall_minicap(self):
        pass


class PagePollApp:
    """Run the real UI page poll and real native button matching against fixture pixels."""

    appear = ModuleBase.appear
    appear_then_click = ModuleBase.appear_then_click
    ensure_button = ModuleBase.ensure_button
    get_interval_timer = ModuleBase.get_interval_timer
    interval_reset = ModuleBase.interval_reset
    interval_clear = ModuleBase.interval_clear
    match_template_color = ModuleBase.match_template_color
    image_crop = ModuleBase.image_crop
    ui_get_current_page = UI.ui_get_current_page
    ui_page_appear = UI.ui_page_appear

    def __init__(self, on_click=None, command='OpsiExplore'):
        self.interval_timer = {}
        self.config = SimpleNamespace(
            BUTTON_OFFSET=30,
            Emulator_ControlMethod='ADB',
            Emulator_ScreenshotMethod='ADB',
            SERVER='cn',
            task=SimpleNamespace(command=command),
        )
        self.device = ClickContractDevice(POPUP_FRAME, on_click=on_click)
        self.device.screenshot = lambda: self.device.image
        self.device.app_is_running = lambda: True
        self.device.get_orientation = lambda: 1
        self.device.uninstall_minicap = lambda: None

    def ui_additional(self, get_ship=True):
        return False


class StrategicSearchPopupRecoveryTest(unittest.TestCase):
    def setUp(self):
        # Each test uses fresh button timing/cache state.
        for button in (STRATEGIC_SEARCH_POPUP_CHECK, POPUP_CANCEL, POPUP_CONFIRM):
            button.clear_offset()

    def test_page_poll_cancels_only_known_popup_and_reaches_map(self):
        app = PagePollApp(on_click=lambda: setattr(app.device, 'image', MAP_FRAME))
        self.assertTrue(app.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)))
        self.assertTrue(app.match_template_color(POPUP_CANCEL, offset=(20, 20)))
        with patch('module.base.timer.time', FakeClock()):
            page = app.ui_get_current_page()
        self.assertIs(page, page_os)
        self.assertEqual(len(app.device.clicked), 1)
        self.assertEqual(list(app.device.click_record), [str(POPUP_CANCEL)])
        self.assertFalse(app.appear(POPUP_CONFIRM, offset=(20, 20)))

    def test_persistent_popup_is_bounded_to_three_cancel_attempts(self):
        app = PagePollApp()
        clock = FakeClock()
        click_times = []
        click_adb = app.device.click_adb

        def record_click(x, y):
            click_times.append(clock.now)
            click_adb(x, y)

        app.device.click_adb = record_click
        with patch('module.base.timer.time', clock):
            with self.assertRaisesRegex(RequestHumanTakeover, 'Strategic-search settings popup'):
                app.ui_get_current_page()
        self.assertEqual(len(app.device.clicked), 3)
        self.assertEqual(list(app.device.click_record), [str(POPUP_CANCEL)] * 3)
        self.assertTrue(all(later - earlier >= 2
                            for earlier, later in zip(click_times, click_times[1:])))
        left, top, right, bottom = POPUP_CANCEL.area
        self.assertTrue(all(left <= x <= right and top <= y <= bottom
                            for x, y in app.device.clicked))

    def test_missing_title_does_not_click_cancel(self):
        app = PagePollApp()
        original_appear = app.appear

        def without_title(button, *args, **kwargs):
            if button is STRATEGIC_SEARCH_POPUP_CHECK:
                return False
            return original_appear(button, *args, **kwargs)

        app.appear = without_title
        with patch('module.base.timer.time', FakeClock()):
            with self.assertRaises(GamePageUnknownError):
                app.ui_get_current_page()
        self.assertEqual(app.device.clicked, [])

    def test_missing_cancel_template_or_color_does_not_click(self):
        app = PagePollApp()
        app.match_template_color = lambda button, **kwargs: False
        with patch('module.base.timer.time', FakeClock()):
            with self.assertRaises(GamePageUnknownError):
                app.ui_get_current_page()
        self.assertEqual(app.device.clicked, [])

    def test_each_page_poll_invocation_gets_a_fresh_attempt_bound(self):
        app = PagePollApp()
        with patch('module.base.timer.time', FakeClock()):
            with self.assertRaises(RequestHumanTakeover):
                app.ui_get_current_page()
            self.assertEqual(len(app.device.clicked), 3)
            app.device.on_click = lambda: setattr(app.device, 'image', MAP_FRAME)
            self.assertIs(app.ui_get_current_page(), page_os)
        self.assertEqual(len(app.device.clicked), 4)

    def test_active_cross_month_uses_protected_failure_prefix(self):
        app = PagePollApp(command='OpsiCrossMonth')
        with patch('module.base.timer.time', FakeClock()):
            with self.assertRaisesRegex(
                    RequestHumanTakeover, 'Overdue OpsiCrossMonth cannot confirm'):
                app.ui_get_current_page()
        self.assertEqual(len(app.device.clicked), 3)

    def test_existing_map_page_returns_without_clicks(self):
        app = PagePollApp()
        app.device.image = MAP_FRAME
        self.assertIs(app.ui_get_current_page(), page_os)
        self.assertEqual(app.device.clicked, [])


if __name__ == '__main__':
    unittest.main()
