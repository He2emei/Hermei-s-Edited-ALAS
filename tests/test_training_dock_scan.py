"""Regression tests for the deployment dock scan that ran into the click guard.

Dump 1789964411956 (2026-09-21 12:20:11, alas / OpsiHazard1Leveling, deployment
dock slot 5, faction filter ``iron``):

- ``DOCK_SCROLL`` is calibrated as (1239, 76, 1248, 641) while the scrollbar
  track ends near y=626.  On the archived frame the thumb measures y 326..626,
  so the highest position the scroll can report is
  (400.0-150.5)/(565-301) = 0.9451.
- ``Scroll.at_bottom()`` needs > 0.95 and ``Scroll.set(1.0)`` needs the position
  to improve by ``drag_threshold`` = 0.05: the residual gap is 0.054924, so
  neither of them ever fires.
- ``TrainingFleetManager._scan_selection()`` therefore never saw the end of the
  list, kept asking the scrollbar for position 1.0 and swiped 12 times.  Every
  swipe is recorded by ``Device.click_record_add()``, so
  ``Device.click_record_check()`` aborted the whole task with
  ``GameTooManyClickError`` after 13 s of swiping.

Dump 1790380371763 (2026-09-26 07:52:51, alas / OpsiHazard1Leveling, deployment
dock slot 6, faction filter ``vichya``) is the same crash with a longer thumb:

- The thumb measures y 159..626 (length 468), so the same over-long track
  saturated at (316.5-234.0)/(565-468) = 0.8505.
- The stall guard that was added for the first dump did not fire either: the
  first frame after each swipe still showed the drag's overscroll bounce, where
  the thumb is drawn shorter and lower (length 441, position 0.77), and the old
  judgement read that 0.08 jump as movement.

Both crashes come from measurement noise around an unreachable position, so the
tests below pin the calibrated track, the positions measured on the archived
frames and the settled-frame judgement.
"""
import collections
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from module.base.button import Button
from module.device.device import Device
from module.exception import GameTooManyClickError, RequestHumanTakeover
from module.os.training import TrainingFleetManager
from module.os.training_policy import ShipCandidate
from module.os.training_ui import (TrainingShipInspector, catalog_name,
                                   reading_similarity, same_dock_page)
from module.retire.dock import DOCK_SCROLL
from module.ui.scroll import Scroll

# Positions measured on the crash frame: the thumb length, the calibrated
# track and the highest position the scrollbar can report.
THUMB_LENGTH = 301
TRACK_END = 0.9450757575757576
# Thumb colour measured on the archived frames (the calibrated colour is
# (247, 211, 66), which color_similarity_2d matches with 34 levels of slack).
THUMB_COLOR = (244, 206, 65)


def card(name):
    return Button((0, 0, 10, 10), (0, 0, 0), (0, 0, 10, 10), name=name)


class Main:
    """Minimal stand-in for ModuleBase: Scroll only needs ``device``."""

    def __init__(self, device):
        self.device = device


class FrameMain:
    """ModuleBase stand-in that serves a synthetic frame to Scroll."""

    def __init__(self, image):
        self.image = image

    def image_crop(self, area, copy=True):
        return self.image[area[1]:area[3], area[0]:area[2]]


def dock_frame(thumb):
    """A 1280x720 frame whose dock scrollbar thumb covers the rows ``thumb``."""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[thumb[0]:thumb[1] + 1, 1239:1248] = THUMB_COLOR
    return image


class ProbeTimer:
    """``Timer(1, count=2)`` without the waiting.

    ``clear()`` keeps the real fast first try and ``reached()`` then needs two
    accesses, like the real timer.  Those extra accesses are the frames the
    scrollbar settles on, so the probe keeps them.
    """

    def __init__(self):
        self.calls = 1

    def clear(self):
        self.calls = 1

    def reset(self):
        self.calls = 0

    def reached(self):
        self.calls += 1
        return self.calls % 2 == 0


class ProbeScroll(Scroll):
    """A dock scrollbar whose position is reported from a model, not pixels."""

    def __init__(self, position, end, page_step):
        # The probe reports its position from a model, so the area only feeds
        # the swipe geometry.  It keeps the over-long calibration the two dumps
        # were measured on, which is what makes the modelled end unreachable.
        super().__init__((1239, 76, 1248, 641), (247, 211, 66), name='DOCK_SCROLL')
        self.length = THUMB_LENGTH
        self.position = position
        self.end = end
        self.page_step = page_step

    def ready(self):
        """Let every drag attempt run without waiting for the real timers."""
        self.drag_interval = ProbeTimer()
        self.drag_timeout = collections.namedtuple('_Timer', 'reset reached')(
            lambda: None, lambda: False)
        return self

    def cal_position(self, main):
        return self.position


class BouncingScroll(ProbeScroll):
    """The scrollbar of dump 1790380371763: the frame after a swipe still shows
    the drag's overscroll bounce.

    The log reports the settled position 0.85 (``(316.5-234.0)/(565-468)``) and
    0.77 (``(316.2-220.5)/(565-441)``) right after each swipe.
    """

    bounce_offset = 0.08

    def __init__(self, position, end, page_step):
        super().__init__(position, end, page_step)
        self.bounce = False

    def cal_position(self, main):
        if self.bounce:
            self.bounce = False
            return self.position - self.bounce_offset
        return self.position


class ProbeDevice:
    """Device stub bound to the real click guard.

    ``click_record*`` come from :class:`Device`, so a runaway scan fails through
    exactly the check that ended the production task.
    """

    click_record_add = Device.click_record_add
    click_record_check = Device.click_record_check
    click_record_clear = Device.click_record_clear

    def __init__(self, scroll, step):
        self.scroll = scroll
        self.step = step
        self.image = None
        self.click_record = collections.deque(maxlen=15)
        self.swipes = []

    def screenshot(self):
        return None

    def sleep(self, seconds):
        return None

    def click(self, button, control_check=True):
        return None

    def swipe(self, p1, p2, duration=(0.1, 0.2), name='SWIPE', distance_check=True):
        # Control.swipe() records the control before dropping a short swipe,
        # and the dock follows the finger, capped by the end of the list.
        self.click_record_add(name)
        self.click_record_check()
        self.swipes.append(name)
        if distance_check and np.linalg.norm(np.subtract(p1, p2)) < 10:
            return
        direction = 1 if p2[1] > p1[1] else -1
        self.scroll.position = min(max(self.scroll.position + direction * self.step, 0.0),
                                   self.scroll.end)


class BouncingDevice(ProbeDevice):
    """ProbeDevice whose scrollbar bounces on the frame after every swipe."""

    def swipe(self, *args, **kwargs):
        super().swipe(*args, **kwargs)
        self.scroll.bounce = True


class ScanManager(TrainingFleetManager):
    """TrainingFleetManager whose dock OCR follows the probe position."""

    def __init__(self, device, scroll, pages):
        self.device = device
        self.scroll = scroll
        self.pages = pages

    def _visible_names(self):
        index = min(round(self.scroll.position / self.scroll.page_step), len(self.pages) - 1)
        raw = list(self.pages[index])
        self._raw_names = raw
        self._visible_cards = [card(f'CARD_{i}') for i in range(len(raw))]
        return [catalog_name(n) for n in raw]


class DockScrollTrackTest(unittest.TestCase):
    """The dock scrollbar track ends at y=626, not at the asset's y=641.

    Measured on the archived frames: the thumb bottoms out at y=626 in dump
    1790380371763 (thumb y 159..626, length 468) and in dump 1789964197466
    (thumb y 326..626, length 301), while the dock scrolled to its top draws
    the thumb from y=69 (2026-09-10 frame, length 107).  The JP asset is
    78..628, i.e. the same 550 px track.
    """

    def test_the_track_is_calibrated_to_the_measured_height(self):
        self.assertEqual(DOCK_SCROLL.area, (1239, 76, 1248, 626))

    def test_the_end_of_the_list_reports_position_one(self):
        for thumb in ((159, 626), (326, 626)):
            with self.subTest(thumb=thumb):
                main = FrameMain(dock_frame(thumb))
                position = DOCK_SCROLL.cal_position(main)
                # The area's bottom row is the exclusive end of the crop, so the
                # thumb's last row is not measured and the reading lands just
                # under 1.0: what matters is that it clears at_bottom() and
                # that set(1.0) can converge on it.
                self.assertGreater(position, 1 - DOCK_SCROLL.edge_threshold)
                self.assertLess(abs(1 - position), DOCK_SCROLL.drag_threshold)
                self.assertTrue(DOCK_SCROLL.at_bottom(main))

    def test_the_top_of_the_list_reports_position_zero(self):
        # The thumb is drawn from y=69 here, above the calibrated area, and the
        # mask is clipped to the area; the top must still read as 0.
        main = FrameMain(dock_frame((69, 175)))
        self.assertEqual(DOCK_SCROLL.cal_position(main), 0.0)
        self.assertTrue(DOCK_SCROLL.at_top(main))

    def test_a_thumb_filling_the_track_does_not_break_the_measurement(self):
        main = FrameMain(dock_frame((76, 626)))
        self.assertEqual(DOCK_SCROLL.cal_position(main), 0.0)


class ScrollStallTest(unittest.TestCase):
    """Scroll.set() must give up on a position the scroll cannot reach."""

    def test_scroll_stops_swiping_at_the_end_of_the_track(self):
        scroll = ProbeScroll(position=TRACK_END, end=TRACK_END, page_step=TRACK_END).ready()
        device = ProbeDevice(scroll, step=0.5)
        dragged = scroll.set(1.0, main=Main(device))
        self.assertEqual(dragged, scroll.stall_limit)
        self.assertEqual(device.swipes, ['DOCK_SCROLL'] * scroll.stall_limit)
        self.assertEqual(scroll.position, TRACK_END)

    def test_scroll_still_reaches_a_position_inside_the_track(self):
        scroll = ProbeScroll(position=0.0, end=TRACK_END, page_step=0.45).ready()
        device = ProbeDevice(scroll, step=0.45)
        dragged = scroll.set(0.45, main=Main(device))
        self.assertEqual(dragged, 1)
        self.assertAlmostEqual(scroll.position, 0.45)

    def test_scroll_still_reaches_the_track_top(self):
        scroll = ProbeScroll(position=TRACK_END, end=TRACK_END, page_step=0.45).ready()
        device = ProbeDevice(scroll, step=0.45)
        dragged = scroll.set(0.0, main=Main(device))
        self.assertGreater(dragged, 0)
        self.assertLess(dragged, scroll.stall_limit)
        self.assertLess(abs(scroll.position), scroll.drag_threshold)

    def test_the_probe_device_reproduces_the_click_guard(self):
        # The stub is only useful if it aborts like the production device does.
        scroll = ProbeScroll(position=TRACK_END, end=TRACK_END, page_step=TRACK_END).ready()
        device = ProbeDevice(scroll, step=0.5)
        main = Main(device)
        with self.assertRaises(GameTooManyClickError):
            for _ in range(20):
                scroll.set(1.0, main=main)


class ScrollSettleTest(unittest.TestCase):
    """A swipe is judged on the settled scrollbar, not on the frame after it."""

    def test_a_bouncing_thumb_does_not_hide_an_unreachable_position(self):
        # Dump 1790380371763: the thumb saturates at 0.85 and every swipe is
        # followed by a bounce frame that reports 0.77.
        scroll = BouncingScroll(position=0.85, end=0.85, page_step=0.85).ready()
        device = BouncingDevice(scroll, step=0.5)
        dragged = scroll.set(1.0, main=Main(device))
        self.assertEqual(dragged, scroll.stall_limit)
        self.assertEqual(device.swipes, ['DOCK_SCROLL'] * scroll.stall_limit)
        self.assertEqual(scroll.position, 0.85)

    def test_a_bouncing_thumb_still_reaches_a_reachable_position(self):
        scroll = BouncingScroll(position=0.0, end=0.85, page_step=0.45).ready()
        device = BouncingDevice(scroll, step=0.45)
        dragged = scroll.set(0.45, main=Main(device))
        self.assertGreaterEqual(dragged, 1)
        self.assertAlmostEqual(scroll.position, 0.45)


class DockPageReadingTest(unittest.TestCase):
    """The repeated-page check has to tolerate cnocr noise."""

    def test_readings_of_one_card_agree_despite_dropped_and_stray_characters(self):
        for left, right in (
                ('_德意志', '德意志'),
                ('、珍珠号', '珍珠号_'),
                ('斯佩伯爵海军上…', '斯佩伯爵海军上'),
                ('反击', '反共'),
                ('、英仙座', '英仙座'),
                ('Z23', 'Z23'),
        ):
            with self.subTest(left=left, right=right):
                self.assertGreaterEqual(reading_similarity(left, right), 0.5)

    def test_unrelated_names_stay_below_the_page_threshold(self):
        for left, right in (('Z20', 'Z46'), ('企业', '柴郡'), ('德意志', '希佩尔海军上将')):
            with self.subTest(left=left, right=right):
                self.assertLess(reading_similarity(left, right), 0.5)

    def test_only_a_reading_of_the_same_cards_is_the_same_page(self):
        page = ['_德意志', '希佩尔海军上将', 'Z23']
        self.assertTrue(same_dock_page(page, ['德意志_', '希佩尔海军上将_', 'Z23']))
        self.assertFalse(same_dock_page(page, ['企业', '柴郡', 'Z46']))
        self.assertFalse(same_dock_page(page, page[:2]))
        self.assertFalse(same_dock_page(page, []))
        self.assertFalse(same_dock_page([], page))


class DeploymentDockScanTest(unittest.TestCase):
    """The scan has to end at the last page instead of swiping into the guard."""

    def manager(self, pages, position, end, page_step, step):
        scroll = ProbeScroll(position, end, page_step).ready()
        device = ProbeDevice(scroll, step=step)
        return ScanManager(device, scroll, pages), device, scroll

    def scan(self, manager, scroll, target=None):
        with patch('module.os.training.DOCK_SCROLL', scroll):
            return manager._scan_selection(target)

    def test_scan_collects_every_page_and_ends_at_the_track_end(self):
        pages = [['德意志', '希佩尔海军上将', 'Z23'],
                 ['Z19', '卡尔斯鲁厄', '柯尼斯堡'],
                 ['罗恩', '美因茨', '埃尔宾']]
        manager, device, scroll = self.manager(pages, position=0.0, end=TRACK_END,
                                               page_step=TRACK_END / 2, step=TRACK_END / 2)
        turns = []
        real_next_page = scroll.next_page
        scroll.next_page = lambda main, page=0.45: (turns.append(page),
                                                    real_next_page(main=main, page=page))[1]
        names = self.scan(manager, scroll)
        self.assertEqual(names, {name for page in pages for name in page})
        # One page turn per page read; the last one is the turn the dock cannot
        # follow, which is how this loop learns where the list ends.
        self.assertLessEqual(len(turns), len(pages))
        self.assertLess(len(device.swipes), 12)

    def test_scan_stops_on_a_repeated_page_read_with_ocr_noise(self):
        # The thumb inches forward while the cards stay the same, so only the
        # tolerant page comparison can tell that the dock is not advancing.
        pages = [['德意志', '希佩尔海军上将', 'Z23'],
                 ['德意志', '希佩尔海军上将', 'Z23']]
        manager, device, scroll = self.manager(pages, position=0.87, end=TRACK_END,
                                               page_step=TRACK_END, step=0.06)
        turns = []
        real_next_page = scroll.next_page
        scroll.next_page = lambda main, page=0.45: (turns.append(page),
                                                    real_next_page(main=main, page=page))[1]
        readings = iter([['卡尔斯鲁厄', 'Z23', '德意志'],
                         ['尔斯鲁厄', 'Z23', '德意志']])

        def visible_names():
            raw = list(next(readings, ['尔斯鲁厄', 'Z23', '德意志']))
            manager._raw_names = raw
            manager._visible_cards = [card(f'CARD_{i}') for i in range(len(raw))]
            return [catalog_name(n) for n in raw]

        manager._visible_names = visible_names
        names = self.scan(manager, scroll)
        # The dropped 卡 leaves the second reading unresolvable, so the exact
        # comparison the scan used before sees a different page here.
        self.assertEqual(names, {'卡尔斯鲁厄', 'Z23', '德意志'})
        self.assertEqual(len(turns), 1)
        self.assertLess(len(device.swipes), 12)

    def test_scan_reports_a_missing_target_instead_of_swiping_forever(self):
        pages = [['德意志', 'Z23']]
        manager, device, scroll = self.manager(pages, position=TRACK_END, end=TRACK_END,
                                               page_step=TRACK_END, step=0.0)
        with self.assertRaises(RequestHumanTakeover):
            self.scan(manager, scroll, target='企业')
        self.assertLess(len(device.swipes), 12)

    def test_candidate_scan_ends_when_the_dock_cannot_scroll_further(self):
        # find_candidates() walks the same dock and has the same end condition.
        scroll = ProbeScroll(position=TRACK_END, end=TRACK_END, page_step=TRACK_END).ready()
        device = ProbeDevice(scroll, step=0.5)
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = lambda *args, **kwargs: None
        inspector.dock_favourite_set = lambda *args, **kwargs: None
        inspector.dock_sort_method_dsc_set = lambda *args, **kwargs: None
        inspector.dock_filter_set = lambda *args, **kwargs: None
        inspector.ship_info_enter = lambda *args, **kwargs: None
        inspector.wait_until_appear = lambda *args, **kwargs: True
        inspector.device = device
        inspector.appear = lambda *args, **kwargs: False
        ship = ShipCandidate('德意志', '铁血', 'vanguard', 120, False, True, None, 120)
        inspector.read_ship = lambda: ship
        with patch('module.os.training_ui.DOCK_SCROLL.set_top'), \
                patch('module.os.training_ui.dock_cards', return_value=[card('DOCK_CARD')]), \
                patch('module.os.training_ui.dock_card_lock', return_value=True), \
                patch('module.os.training_ui.LevelOcr') as level, \
                patch('module.os.training_ui.Ocr') as ocr, \
                patch('module.os.training_ui.decide_trainability',
                      return_value=SimpleNamespace(allowed=True, reason='probe')):
            level.return_value.ocr.return_value = [120]
            ocr.return_value.ocr.return_value = ['德意志']
            found = inspector.find_candidates('vanguard', frozenset(), set(), needed=2,
                                              scroll=scroll)
        self.assertEqual([candidate.name for candidate in found], ['德意志'])
        self.assertLess(len(device.swipes), 12)


if __name__ == '__main__':
    unittest.main()
