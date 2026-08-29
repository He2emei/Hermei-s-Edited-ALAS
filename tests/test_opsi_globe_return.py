import unittest
from unittest.mock import patch

from module.os.assets import GLOBE_GOTO_MAP, ZONE_ENTRANCE
from module.os.globe_operation import GlobeOperation
from module.os_handler.assets import MISSION_QUIT, STORAGE_ENTER
from module.os_handler.storage import StorageHandler


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


class OpsiGlobeReturnTest(unittest.TestCase):
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
