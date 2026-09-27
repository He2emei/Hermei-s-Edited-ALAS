"""Regression tests for the enhancement material de-select loop.

Live incident: 2026-09-27 15:06:22 (dump log/error/1790492782871, frame
tests/fixtures/enhance_deselect/selection-list-20260927.png).  GemsFarming was
enhancing ships, 推荐 filled the material slots of a ship with a common rarity CV
(突击者), _enhance_deselect_cv() clicked that material card, the exit test - a '+'
search in a box around the matched portrait - did not see the empty slot that
appeared, so the loop clicked the same spot again 2 s later, and that click landed
on the now empty slot's '+', which opens the material-selection list.  That list has
no ENHANCE_RECOMMEND and no exit inside the loop, so no further click was sent and
Device.stuck_record_check() raised GameStuckError: Wait too long exactly 60 s after
the last click.  Twelve dumps between 2026-09-09 and 2026-09-27 carry the same
traceback (enhancement.py L169 _enhance_deselect_cv) and the same frame.

The portraits used by the de-select (TEMPLATE_ENHANCE_*) are 42x18 / 42x22 crops of
the ship's eye region, which is not centred in the 82x82 material slot cell, while
the game draws the empty slot '+' at the cell centre: anything derived from a
portrait match has to be snapped back to the slot grid.
"""
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2

from module.base.button import Button
from module.exception import GameStuckError
from module.retire.assets import EMPTY_ENHANCE_SLOT_PLUS, ENHANCE_RECOMMEND, EQUIP_CONFIRM
from module.retire.enhancement import (ENHANCE_DESELECT_MAX_CLICK, ENHANCE_SLOT_COUNT,
                                       Enhancement, enhance_slot_area, enhance_slot_center,
                                       enhance_slot_index)
from module.ui.ui import UI

FIXTURES = Path(__file__).parent / 'fixtures'
ENHANCE_FIXTURES = FIXTURES / 'enhance_deselect'
# 2026-05-13 06:21:52 (dump log/error/1778624512548, GameTooManyClickError:
# ENHANCE_CONFIRM): two material cards in row 1, the other ten slots show '+'.
EMPTY_SLOTS = ENHANCE_FIXTURES / 'empty-slots-20260513.png'
# 2026-06-15 04:07:01 (dump log/error/1781467621394): twelve material cards, 博格 in
# the second cell, i.e. a real TEMPLATE_ENHANCE_BOGUE match to drive the loop with.
MATERIAL_CARDS = ENHANCE_FIXTURES / 'material-cards-20260615.png'
# 2026-09-27 15:06:22 (dump log/error/1790492782871): the material-selection list the
# retry click opened, 已选中 1/12.
SELECTION_LIST = ENHANCE_FIXTURES / 'selection-list-20260927.png'
# A dock page: the selection list shares its 船坞 header, this one must not match.
DOCK_PAGE = FIXTURES / 'opsi_lock_dock_alas2_20260925.png'


def load_frame(path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None, f'cannot read {path}'
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def one_common_cv_frame():
    """The 2026-06-15 frame with the second cell emptied, the way the game shows a
    de-selected material: the whole cell is replaced by a real empty cell of the
    2026-05-13 frame (background and '+'), so the first cell still holds a 博格 card.
    """
    image = load_frame(MATERIAL_CARDS)
    source = load_frame(EMPTY_SLOTS)
    image[377:459, 805:887] = source[377:459, 897:979]
    return image


class EnhanceDevice:
    """Device stub that serves archived frames and counts clicks and screenshots."""

    def __init__(self, frames, screenshot_budget=200):
        self.frames = list(frames)
        self.screenshot_budget = screenshot_budget
        self.screenshots = 0
        self.clicks = []
        self.image = self.frames[0]
        self.click_record = deque(maxlen=15)

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > self.screenshot_budget:
            raise AssertionError(
                f'the loop did not stop after {self.screenshot_budget} screenshots')
        # the next frame once something has been clicked
        self.image = self.frames[min(len(self.clicks), len(self.frames) - 1)]
        return self.image

    def click(self, button, control_check=True, **kwargs):
        self.clicks.append(button)

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

    def sleep(self, _seconds):
        return None


def enhance_runner(frames):
    """An Enhancement with real detection and a stand-in device."""
    runner = Enhancement.__new__(Enhancement)
    runner.device = EnhanceDevice(frames)
    runner.config = SimpleNamespace(
        SERVER='cn',
        is_task_enabled=lambda *args, **kwargs: True,
        cross_get=lambda *args, **kwargs: 'any',
    )
    runner.interval_timer = {}
    return runner


class EnhanceSlotGridTest(unittest.TestCase):
    def test_the_plus_asset_sits_on_the_first_cell(self):
        area = EMPTY_ENHANCE_SLOT_PLUS.area
        cx, cy = (area[0] + area[2]) / 2, (area[1] + area[3]) / 2
        gx, gy = enhance_slot_center(0)
        self.assertLess(abs(cx - gx), 4, f'asset centre {cx} vs cell centre {gx}')
        self.assertLess(abs(cy - gy), 4, f'asset centre {cy} vs cell centre {gy}')

    def test_archived_empty_slots_are_located_cell_by_cell(self):
        runner = enhance_runner([load_frame(EMPTY_SLOTS)])
        empty = [index for index in range(ENHANCE_SLOT_COUNT) if runner._enhance_slot_empty(index)]
        self.assertEqual(empty, list(range(2, ENHANCE_SLOT_COUNT)))

    def test_archived_filled_slots_are_not_empty(self):
        runner = enhance_runner([load_frame(MATERIAL_CARDS)])
        empty = [index for index in range(ENHANCE_SLOT_COUNT) if runner._enhance_slot_empty(index)]
        self.assertEqual(empty, [])

    def test_archived_portrait_match_snaps_to_its_cell(self):
        # the real 博格 match of the 2026-06-15 frame, and the same box 36 px further left
        self.assertEqual(enhance_slot_index((837, 419, 879, 437)), 1)
        self.assertEqual(enhance_slot_index((801, 419, 843, 437)), 1)

    def test_a_match_outside_the_slots_is_not_a_slot(self):
        self.assertIsNone(enhance_slot_index((200, 200, 242, 218)))


class DeselectExitTest(unittest.TestCase):
    """The de-select has to be judged on the slot cell, not on the portrait match."""

    def _runner(self, frames, cv_area=None):
        runner = enhance_runner(frames)
        if cv_area is not None:
            runner._enhance_get_deselect_cv = Mock(return_value=Button(
                area=cv_area, color=(), button=cv_area, name='TEMPLATE_ENHANCE_RANGER_RETIRE'))
        return runner

    def test_a_deselected_slot_is_recognised_after_one_click(self):
        frame = one_common_cv_frame()
        runner = self._runner([load_frame(MATERIAL_CARDS), frame])
        with patch('module.retire.enhancement.ENHANCE_DESELECT_CLICK_INTERVAL', 0):
            runner._enhance_deselect_cv()
        self.assertEqual([str(button) for button in runner.device.clicks], ['ENHANCE_SLOT_1'])
        # the click target is the centre of the cell that held the common CV, the
        # area the archived runs de-selected from
        clicked = runner.device.clicks[0]
        self.assertEqual(clicked.button, enhance_slot_area(1))
        x1, y1, x2, y2 = clicked.button
        self.assertTrue(805 <= x1 and x2 <= 887 and 377 <= y1 and y2 <= 459,
                        f'click target {clicked.button} outside the second material cell')

    def test_off_centre_portrait_does_not_reclick_the_empty_slot(self):
        # 2026-09-27: the portrait match sat far enough from the cell centre that the
        # old '+'-in-a-box test could not see the empty slot.  Clicking again opened
        # the material-selection list and the run died on the 60s stuck check.
        runner = self._runner([one_common_cv_frame()], cv_area=(801, 419, 843, 437))
        runner._enhance_deselect_cv()
        self.assertEqual(runner.device.clicks, [])

    def test_an_ignored_click_is_bounded(self):
        runner = self._runner([load_frame(MATERIAL_CARDS)])
        with patch('module.retire.enhancement.ENHANCE_DESELECT_CLICK_INTERVAL', 0):
            runner._enhance_deselect_cv()
        self.assertEqual(len(runner.device.clicks), ENHANCE_DESELECT_MAX_CLICK)

    def test_no_click_without_a_common_cv(self):
        runner = self._runner([load_frame(EMPTY_SLOTS)])
        runner._enhance_deselect_cv()
        self.assertEqual(runner.device.clicks, [])


class SelectionListTest(unittest.TestCase):
    """The material-selection list must be recognised and cancelled, not spun on."""

    def test_archived_crash_frame_is_the_selection_list(self):
        runner = enhance_runner([load_frame(SELECTION_LIST)])
        self.assertTrue(runner._enhance_selection_page())

    def test_the_ship_detail_page_and_the_dock_are_not_the_selection_list(self):
        self.assertFalse(enhance_runner([load_frame(MATERIAL_CARDS)])._enhance_selection_page())
        self.assertFalse(enhance_runner([load_frame(DOCK_PAGE)])._enhance_selection_page())

    def test_the_handler_cancels_the_list(self):
        runner = enhance_runner([load_frame(SELECTION_LIST), load_frame(MATERIAL_CARDS)])
        self.assertTrue(runner.handle_enhance_selection_page())
        self.assertEqual([str(button) for button in runner.device.clicks], ['ENHANCE_SELECT_CANCEL'])

    def test_the_handler_is_a_no_op_on_the_ship_detail_page(self):
        runner = enhance_runner([load_frame(MATERIAL_CARDS)])
        self.assertFalse(runner.handle_enhance_selection_page())
        self.assertEqual(runner.device.clicks, [])


class RecommendStateWiringTest(unittest.TestCase):
    """state_enhance_recommend() must cancel the list before judging the slots."""

    def test_the_recommend_state_cancels_the_open_list_first(self):
        # The list is open; cancelling it returns to the ship detail page whose first
        # cell holds a 博格 card and whose second cell is empty, so the state machine
        # takes the "Only 1 common CV material" path and exits the category.
        frames = [load_frame(SELECTION_LIST), one_common_cv_frame()]
        runner = enhance_runner(frames)
        self.assertFalse(EQUIP_CONFIRM.match(runner.device.image, offset=(30, 30)))

        runner.ship_side_navbar_ensure = Mock(return_value=True)
        runner.wait_until_appear = Mock(return_value=None)
        runner.info_bar_count = Mock(return_value=0)
        runner.handle_popup_confirm = Mock(return_value=False)
        runner.ship_view_next = Mock(return_value=True)
        real_appear_then_click = UI.appear_then_click

        def appear_then_click(button, **kwargs):
            if str(button) == str(ENHANCE_RECOMMEND):
                return True
            return real_appear_then_click(runner, button, **kwargs)

        runner.appear_then_click = appear_then_click
        result, ship_count = runner._enhance_choose(ship_count=1)
        self.assertFalse(result)
        self.assertEqual([str(button) for button in runner.device.clicks], ['ENHANCE_SELECT_CANCEL'])


if __name__ == '__main__':
    unittest.main()
