import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from module.os.assets import GLOBE_GOTO_MAP, ZONE_ENTRANCE
from module.os.globe_operation import GlobeOperation
from module.os.map import OSMap
from module.os_handler.assets import STRATEGIC_SEARCH_MAP_OPTION_OFF, STRATEGIC_SEARCH_POPUP_CHECK
from module.os_handler.assets import MISSION_QUIT, STORAGE_ENTER
from module.os_handler.storage import StorageHandler
from module.ui.page import page_os


class ImmediateTimer:
    def __init__(self, *args, **kwargs):
        pass

    def reached(self):
        return True

    def start(self):
        return self

    def reset(self):
        return self

    def clear(self):
        return self


class FakeDevice:
    def __init__(self, owner):
        self.owner = owner
        self.clicks = []

    def click(self, button):
        self.clicks.append(str(button))
        if button == GLOBE_GOTO_MAP:
            self.owner.page = 'operation_info'
        elif button == MISSION_QUIT:
            self.owner.page = 'globe_after_info'
        elif button == ZONE_ENTRANCE:
            self.owner.page = 'map'
        elif button == STORAGE_ENTER:
            self.owner.page = 'storage'


class OpsiNavigationHarness:
    def __init__(self, page='globe'):
        self.page = page
        self.device = FakeDevice(self)
        self.info_bar_handled = False

    def loop(self, *args, **kwargs):
        for _ in range(20):
            yield None

    def ui_click(self, click_button, **kwargs):
        # Legacy os_globe_goto_map() delegates to ui_click() and returns after
        # the first click, which reproduces the production failure.
        self.device.click(click_button)
        return True

    def is_in_globe(self):
        return self.page in {'globe', 'globe_after_info'}

    def is_in_map(self):
        return self.page == 'map'

    def is_in_storage(self):
        return self.page == 'storage'

    def appear(self, button, **kwargs):
        return button == MISSION_QUIT and self.page == 'operation_info'

    def appear_then_click(self, button, **kwargs):
        visible = (
            (button == MISSION_QUIT and self.page == 'operation_info')
            or (button == STORAGE_ENTER and self.page == 'map')
        )
        if visible:
            self.device.click(button)
        return visible

    def handle_map_event(self):
        return False

    def handle_info_bar(self):
        self.info_bar_handled = True


class GlobeReturnHarness(OpsiNavigationHarness, GlobeOperation):
    pass


class StorageReturnHarness(OpsiNavigationHarness, StorageHandler):
    pass


class StrategySearchRecoveryHarness(OSMap):
    def __init__(self, image, page='overview'):
        self.page = page
        self.device = SimpleNamespace(image=image, clicks=[], click_pages=[])
        self.device.stuck_record_add = lambda *_: None
        self.device.click = self._click
        self.config = SimpleNamespace(SERVER='cn')
        self.map_returns = 0

    def _click(self, button):
        self.device.clicks.append(str(button))
        self.device.click_pages.append(self.page)
        if self.page == 'map' and button == STRATEGIC_SEARCH_MAP_OPTION_OFF:
            self.page = 'popup'

    def loop(self, *args, **kwargs):
        for _ in range(3):
            yield None

    def interval_clear(self, *_args, **_kwargs):
        return None

    def is_in_globe(self):
        if self.page == 'overview':
            return OSMap.is_in_globe(self)
        return self.page == 'globe'

    def is_in_map(self):
        if self.page == 'overview':
            return OSMap.is_in_map(self)
        return self.page == 'map'

    def ui_goto_main(self):
        return None

    def os_globe_goto_map(self):
        self.map_returns += 1
        self.page = 'map'

    def appear(self, button, **kwargs):
        if button == GLOBE_GOTO_MAP and self.page == 'overview':
            return button.match(self.device.image, offset=kwargs.get('offset', (30, 30)))
        return button == STRATEGIC_SEARCH_POPUP_CHECK and self.page == 'popup'

    def match_template_color(self, button, **kwargs):
        if self.page == 'overview':
            return OSMap.match_template_color(self, button, **kwargs)
        return button == STRATEGIC_SEARCH_MAP_OPTION_OFF and self.page == 'map'

    def handle_map_event(self):
        return False


class OpsiGlobeReturnTest(unittest.TestCase):
    def test_restart_error_frame_is_globe_not_map_but_matches_page_os(self):
        path = Path(__file__).parent / 'fixtures' / 'opsi_overview_globe_restart_20261015.png'
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        opsi = object.__new__(OSMap)
        opsi.device = SimpleNamespace(image=image, stuck_record_add=lambda *_: None)
        opsi.config = SimpleNamespace(SERVER='cn')

        self.assertFalse(opsi.is_in_map())
        self.assertTrue(opsi.is_in_globe())
        self.assertTrue(opsi.ui_page_appear(page_os))

    def test_strategy_search_normalizes_globe_before_trying_map_option(self):
        path = Path(__file__).parent / 'fixtures' / 'opsi_overview_globe_restart_20261015.png'
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        opsi = StrategySearchRecoveryHarness(image)
        self.assertTrue(opsi.is_in_globe())

        result = opsi.strategy_search_enter()

        self.assertTrue(result)
        self.assertEqual(opsi.map_returns, 1)
        self.assertEqual(opsi.page, 'popup')
        self.assertEqual(opsi.device.clicks, [str(STRATEGIC_SEARCH_MAP_OPTION_OFF)])
        self.assertEqual(opsi.device.click_pages, ['map'])

    def test_strategy_search_does_not_normalize_unknown_page_as_globe(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        opsi = StrategySearchRecoveryHarness(image, page='unknown')

        opsi.strategy_search_enter()

        self.assertEqual(opsi.map_returns, 0)
        self.assertEqual(opsi.page, 'unknown')

    def test_globe_return_recovers_through_operation_info_overlay(self):
        campaign = GlobeReturnHarness(page='globe')

        with patch('module.os.globe_operation.Timer', ImmediateTimer):
            campaign.os_globe_goto_map()

        self.assertEqual(campaign.page, 'map')
        self.assertEqual(
            campaign.device.clicks,
            [str(GLOBE_GOTO_MAP), str(MISSION_QUIT), str(ZONE_ENTRANCE)],
        )

    def test_storage_enter_recovers_if_overview_reappears_after_globe_return(self):
        campaign = StorageReturnHarness(page='operation_info')

        with patch('module.os.globe_operation.Timer', ImmediateTimer):
            campaign.storage_enter()

        self.assertEqual(campaign.page, 'storage')
        self.assertEqual(
            campaign.device.clicks,
            [str(MISSION_QUIT), str(ZONE_ENTRANCE), str(STORAGE_ENTER)],
        )
        self.assertTrue(campaign.info_bar_handled)


if __name__ == '__main__':
    unittest.main()
