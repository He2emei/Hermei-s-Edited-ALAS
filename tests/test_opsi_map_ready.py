import unittest

from module.os.fleet import OSFleet
from module.os_handler.assets import CLICK_SAFE_AREA
from module.os_shop.assets import PORT_SUPPLY_CHECK


class DelayedAkashiHarness:
    def __init__(self):
        self.page = 'story_option'
        self.events = []
        self._solved_map_event = set()
        self._os_in_map_confirm_timer = self

    def reset(self):
        self.events.append('reset_timer')

    def loop(self):
        for _ in range(5):
            yield None
        raise AssertionError('ensure_os_map_ready did not return to the OpSi map')

    def handle_map_event(self):
        if self.page == 'story_option':
            self.events.append('story_option')
            self.page = 'akashi_shop'
            return 'story_skip'
        return ''

    def appear(self, button, **kwargs):
        return button is PORT_SUPPLY_CHECK and self.page == 'akashi_shop'

    def interval_clear(self, button):
        self.events.append(f'clear:{button}')

    def handle_akashi_supply_buy(self, grid):
        self.events.append(f'buy:{grid}')
        self.page = 'map'

    def handle_os_in_map(self):
        return self.page == 'map'


class OpsiMapReadyTest(unittest.TestCase):
    def test_delayed_akashi_dialog_is_handled_before_map_camera_swipes(self):
        campaign = DelayedAkashiHarness()

        OSFleet.ensure_os_map_ready(campaign)

        self.assertEqual(campaign.page, 'map')
        self.assertIn(f'buy:{CLICK_SAFE_AREA}', campaign.events)
        self.assertIn('is_akashi', campaign._solved_map_event)


if __name__ == '__main__':
    unittest.main()
