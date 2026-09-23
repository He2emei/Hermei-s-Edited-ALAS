"""Regression tests for the dorm training roster that no page check can pass.

Live incident: 2026-09-24 03:49:29 (dump log/error/1790193037515, frame
tests/fixtures/dorm_training_roster/roster-open-0350.png). DormTraining closed the
first-floor training roster with a single tap, the game did not act on that tap
(the device confirmed the tap was delivered, the panel stayed for minutes), the
task aborted with the roster still open, and then every task - Dorm at 03:50:37 and
03:51:39, Commission at 03:56:41 - died in UI.ui_get_current_page() with
GamePageUnknownError, because the roster covers DORM_CHECK and has no HOME button.
"""
import unittest
from collections import Counter, deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2

from module.base.button import Button
from module.base.timer import Timer
from module.dorm.training import (ROSTER_CLOSE_AREA, ROSTER_CLOSE_FALLBACK, DormTraining,
                                  dismiss_training_roster, locate_roster_close,
                                  roster_close_timer)
from module.exception import GamePageUnknownError, GameTooManyClickError, RequestHumanTakeover
from module.ui.assets import DORM_CHECK
from module.ui.page import page_dorm
from module.ui.ui import UI

FIXTURES = Path(__file__).parent / 'fixtures' / 'dorm_training_roster'
ROSTER_OPEN = FIXTURES / 'roster-open-0350.png'
# 2026-01-12 23:56:56, dump log/error/1768233416586, OpsiHazard1Leveling: the same
# roster left open on the rest tab, where the training header is absent.
ROSTER_REST_TAB = FIXTURES / 'roster-rest-tab-0112.png'
OTHER_PAGE = Path(__file__).parent / 'fixtures' / 'new_ship_page' / 'campaign-map.png'


def load_frame(path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None, f'cannot read {path}'
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def roster_closed_frame(open_frame):
    """The same frame with the roster gone: its close icon cleared and the dorm page's
    own check icon drawn where the game draws it.

    The archived frame cannot show the dorm page itself, the roster covers DORM_CHECK.
    The icon is the asset the page check matches, pasted at the asset's own area, so the
    real page_dorm check runs unchanged.
    """
    DORM_CHECK.ensure_template()
    image = open_frame.copy()
    x1, y1, x2, y2 = ROSTER_CLOSE_AREA
    image[y1:y2, x1:x2] = 0
    x1, y1, x2, y2 = DORM_CHECK.area
    image[y1:y2, x1:x2] = DORM_CHECK.image
    return image


class FakeDevice:
    """Device stub that serves the roster until the roster is clicked away."""

    def __init__(self, roster_frame, closed_frame):
        self.roster_frame = roster_frame
        self.closed_frame = closed_frame
        self.clicks = []
        self.click_record = deque(maxlen=15)
        self.image = roster_frame
        self.has_cached_image = False
        self.dismissed = False

    def screenshot(self):
        self.image = self.closed_frame if self.dismissed else self.roster_frame
        return self.image

    def click(self, button, control_check=True, **kwargs):
        self.clicks.append(button)
        if control_check:
            self.click_record.append(str(button))
            count = Counter(self.click_record).most_common(1)[0]
            if count[1] >= 12:
                self.click_record.clear()
                raise GameTooManyClickError(f'Too many click for a button: {count[0]}')
        if str(button) == 'DORM_TRAINING_CLOSE':
            self.dismissed = True

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
        return None

    def app_is_running(self):
        return True

    def get_orientation(self):
        return 1

    def sleep(self, _seconds):
        return None


class FakeUi(UI):
    """Real page checks and the real ui_additional(), without a real game."""

    def __init__(self, device, server='cn'):
        self.device = device
        self.config = SimpleNamespace(SERVER=server, Emulator_ScreenshotMethod='nemu_ipc',
                                      Emulator_ControlMethod='MaaTouch', BUTTON_OFFSET=30)
        self.interval_timer = {}

    def ui_page_os_popups(self):
        return False

    def handle_popup_confirm(self, *args, **kwargs):
        return False

    def handle_urgent_commission(self):
        return False

    def ui_page_main_popups(self, *args, **kwargs):
        return False

    def handle_story_skip(self):
        return False


class RosterTimerCase(unittest.TestCase):
    """Make the roster close interval reached without waiting for it."""

    def setUp(self):
        self._timer_limit = roster_close_timer.limit
        roster_close_timer.limit = 0.05
        roster_close_timer.clear()

    def tearDown(self):
        roster_close_timer.limit = self._timer_limit
        roster_close_timer.clear()


class RosterDetectionTest(RosterTimerCase):
    def test_archived_frame_locates_the_close_icon(self):
        button = locate_roster_close(load_frame(ROSTER_OPEN))
        self.assertIsNotNone(button)
        self.assertEqual(str(button), 'DORM_TRAINING_CLOSE')
        x1, y1, x2, y2 = ROSTER_CLOSE_AREA
        click_x, click_y = (button.button[0] + button.button[2]) / 2, (button.button[1] + button.button[3]) / 2
        self.assertTrue(x1 <= click_x <= x2 and y1 <= click_y <= y2,
                        f'click target {(click_x, click_y)} outside the icon area')

    def test_closed_dorm_page_has_no_roster(self):
        self.assertIsNone(locate_roster_close(roster_closed_frame(load_frame(ROSTER_OPEN))))

    def test_rest_tab_roster_is_located_too(self):
        # The training header is absent on the rest tab, the close icon is not.
        runner = DormTraining.__new__(DormTraining)
        runner.device = SimpleNamespace(image=load_frame(ROSTER_REST_TAB))
        self.assertFalse(runner._training_visible())
        self.assertIsNotNone(locate_roster_close(runner.device.image))

    def test_other_page_has_no_roster(self):
        self.assertIsNone(locate_roster_close(load_frame(OTHER_PAGE)))

    def test_frame_without_the_icon_region_is_not_a_roster(self):
        frame = load_frame(ROSTER_OPEN)
        x1, y1, x2, y2 = ROSTER_CLOSE_AREA
        frame[y1:y2, x1:x2] = 0
        self.assertIsNone(locate_roster_close(frame))


class DismissRosterTest(RosterTimerCase):
    def _ui(self, image, server='cn'):
        device = SimpleNamespace(image=image, click=Mock())
        return FakeUi(device, server=server), device

    def test_dismiss_clicks_the_matched_icon(self):
        image = load_frame(ROSTER_OPEN)
        ui, device = self._ui(image)
        located = locate_roster_close(image)
        self.assertTrue(dismiss_training_roster(ui))
        device.click.assert_called_once()
        clicked = device.click.call_args[0][0]
        self.assertEqual(str(clicked), 'DORM_TRAINING_CLOSE')
        self.assertEqual(clicked.button, located.button)

    def test_dismiss_is_rate_limited_while_the_panel_closes(self):
        ui, device = self._ui(load_frame(ROSTER_OPEN))
        self.assertTrue(dismiss_training_roster(ui))
        self.assertFalse(dismiss_training_roster(ui))
        device.click.assert_called_once()

    def test_dismiss_is_a_no_op_without_the_roster(self):
        ui, device = self._ui(roster_closed_frame(load_frame(ROSTER_OPEN)))
        self.assertFalse(dismiss_training_roster(ui))
        device.click.assert_not_called()

    def test_dismiss_is_a_no_op_on_other_servers(self):
        ui, device = self._ui(load_frame(ROSTER_OPEN), server='en')
        self.assertFalse(dismiss_training_roster(ui))
        device.click.assert_not_called()

    def test_dismiss_closes_the_rest_tab_roster(self):
        ui, device = self._ui(load_frame(ROSTER_REST_TAB))
        self.assertTrue(dismiss_training_roster(ui))
        self.assertEqual(str(device.click.call_args[0][0]), 'DORM_TRAINING_CLOSE')


class UiAdditionalWiringTest(RosterTimerCase):
    def test_ui_additional_closes_the_roster(self):
        device = SimpleNamespace(image=load_frame(ROSTER_OPEN), click=Mock(),
                                 stuck_record_add=Mock())
        ui = FakeUi(device)
        self.assertTrue(ui.ui_additional())
        device.click.assert_called_once()
        self.assertEqual(str(device.click.call_args[0][0]), 'DORM_TRAINING_CLOSE')

    def test_ui_additional_leaves_a_closed_roster_alone(self):
        device = SimpleNamespace(image=roster_closed_frame(load_frame(ROSTER_OPEN)),
                                 click=Mock(), stuck_record_add=Mock())
        ui = FakeUi(device)
        self.assertFalse(ui.ui_additional())
        device.click.assert_not_called()


class UiGetCurrentPageEscapeTest(RosterTimerCase):
    @staticmethod
    def _fast_timer(limit, count=0):
        """The page poll waits ten seconds for a page to appear; a test does not."""
        return Timer(min(limit, 0.5), count=min(count, 5))

    def test_page_identification_escapes_the_roster(self):
        open_frame = load_frame(ROSTER_OPEN)
        device = FakeDevice(open_frame, roster_closed_frame(open_frame))
        ui = FakeUi(device)
        ui.ui_current = None
        page = ui.ui_get_current_page()
        self.assertEqual(page, page_dorm)
        self.assertEqual([str(button) for button in device.clicks], ['DORM_TRAINING_CLOSE'])

    def test_page_identification_still_reports_an_unknown_page_without_a_roster(self):
        # Control: the same frame, but the roster handler is disabled the way it was
        # before the fix, must still end in GamePageUnknownError.
        open_frame = load_frame(ROSTER_OPEN)
        device = FakeDevice(open_frame, roster_closed_frame(open_frame))
        ui = FakeUi(device)
        ui.ui_current = None
        with patch('module.dorm.training.dismiss_training_roster', return_value=False), \
                patch('module.ui.ui.Timer', self._fast_timer):
            with self.assertRaises(GamePageUnknownError):
                ui.ui_get_current_page()
        self.assertEqual(device.clicks, [])

    def test_page_identification_gives_up_instead_of_clicking_forever(self):
        # A roster the game refuses to close is a hung client: the page poll keeps
        # clicking, and the twelve-click protection of the device then restarts the app.
        open_frame = load_frame(ROSTER_OPEN)
        device = FakeDevice(open_frame, open_frame)
        ui = FakeUi(device)
        ui.ui_current = None
        with self.assertRaises(GameTooManyClickError):
            ui.ui_get_current_page()
        self.assertEqual(len(device.clicks), 12)
        self.assertTrue(all(str(button) == 'DORM_TRAINING_CLOSE' for button in device.clicks))


class CloseTrainingRetryTest(unittest.TestCase):
    """The task-side trigger: one dropped tap must not leave the roster open."""

    def _runner(self):
        runner = DormTraining.__new__(DormTraining)
        runner.config = SimpleNamespace(SERVER='cn')
        runner.device = SimpleNamespace(image=load_frame(ROSTER_OPEN), click=Mock())
        runner._training_visible = Mock(return_value=True)
        return runner

    def test_ignored_close_is_retried(self):
        runner = self._runner()
        runner._wait = Mock(side_effect=[RequestHumanTakeover('dorm room'), None])
        runner._close_training()
        self.assertEqual(runner.device.click.call_count, 2)

    def test_repeatedly_ignored_close_reports_human_takeover(self):
        runner = self._runner()
        runner._wait = Mock(side_effect=RequestHumanTakeover('dorm room'))
        with self.assertRaises(RequestHumanTakeover):
            runner._close_training()
        self.assertEqual(runner.device.click.call_count, 3)

    def test_close_uses_the_located_icon(self):
        runner = self._runner()
        runner.device.image = roster_closed_frame(load_frame(ROSTER_OPEN))
        runner._wait = Mock(side_effect=[None])
        runner._close_training()
        self.assertEqual(str(runner.device.click.call_args[0][0]), 'DORM_TRAINING_CLOSE')
        clicked = runner.device.click.call_args[0][0]
        self.assertEqual(str(clicked), str(ROSTER_CLOSE_FALLBACK))


if __name__ == '__main__':
    unittest.main()
