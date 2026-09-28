"""Regression coverage for settled OS shop positions and exact item recovery."""
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2

from module.os_shop.shop import OSShop
from module.os_shop.ui import OS_SHOP_SCROLL

FIXTURES = Path(__file__).parent / 'fixtures' / 'os_shop'


def frame(name):
    image = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    assert image is not None, f'cannot read {name}'
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class FrameDevice:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0
        self.image = self.frames[0]
        self.swipes = []
        self.clicks = []
        self.click_record = ['previous scroll']

    def screenshot(self):
        self.image = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        time.sleep(0.17)
        return self.image

    def swipe(self, start, end, **kwargs):
        self.swipes.append((start, end, kwargs))

    def click(self, button, **kwargs):
        self.clicks.append(button)


class ShopHarness(OSShop):
    @property
    def image(self):
        return self.device.image

    def __init__(self, frames):
        self.device = FrameDevice(frames)
        self.config = SimpleNamespace(SHOP_EXTRACT_TEMPLATE=False)


class OSShopPositionTest(unittest.TestCase):
    def test_viewport_position_and_items_come_from_the_settled_frame(self):
        transient = frame('scan_transient.png')
        settled = frame('bottom_settled.png')
        shop = ShopHarness([transient, transient, settled, settled, settled, settled, settled])
        self.assertAlmostEqual(OS_SHOP_SCROLL.cal_position(main=shop), 0.90808, places=3)

        items, position = shop._os_shop_read_viewport(shop_index=0)

        target = next(item for item in items if item.name == 'LoggerObscureT6')
        self.assertAlmostEqual(position, 0.99858, places=3)
        self.assertEqual((target.price, target.count, target.total_count), (30000, 1, 3))
        self.assertEqual(target.scroll_pos, position)
        self.assertEqual(target.button, (676, 520, 774, 618))
        self.assertGreaterEqual(shop.device.index, 5)

    def test_wrong_hint_viewport_rescans_from_top_and_returns_fresh_target(self):
        top = frame('top_settled.png')
        wrong = frame('wrong_viewport_settled.png')
        bottom = frame('bottom_settled.png')
        shop = ShopHarness([wrong])
        hint = SimpleNamespace(name='LoggerObscureT6', price=30000, shop_index=0,
                               scroll_pos=0.908080808080808, button=(676, 520, 774, 618))
        pages = []
        self.assertIsNone(shop.os_shop_get_items_to_buy('LoggerObscureT6', 30000))

        def set_hint(_position, main, **kwargs):
            main.device.image = wrong

        def set_top(main, **kwargs):
            main.device.image = top

        def next_page(main, page=0.5, **kwargs):
            pages.append(page)
            main.device.image = bottom

        with patch.object(OS_SHOP_SCROLL, 'set', side_effect=set_hint), \
                patch.object(OS_SHOP_SCROLL, 'set_top', side_effect=set_top), \
                patch.object(OS_SHOP_SCROLL, 'next_page', side_effect=next_page), \
                patch.object(shop, 'os_shop_wait_list_stable'):
            found = shop.os_shop_resolve_item_for_purchase(hint)

        self.assertEqual(shop.device.click_record, [])
        self.assertIsNotNone(found)
        self.assertEqual((found.name, found.price, found.count, found.total_count),
                         ('LoggerObscureT6', 30000, 1, 3))
        self.assertEqual(found.button, (676, 520, 774, 618))
        self.assertEqual(found.scroll_pos, 0.9985795454545454)
        self.assertEqual(pages, [0.5])
        self.assertEqual(shop.device.clicks, [])

    def test_missing_target_stops_after_three_stalled_pages_without_clicking(self):
        top = frame('top_settled.png')
        shop = ShopHarness([top])
        hint = SimpleNamespace(name='LoggerObscureT6', price=30000, shop_index=0,
                               scroll_pos=0.8, button=(676, 520, 774, 618))
        pages = []

        def set_hint(_position, main, **kwargs):
            main.device.image = top

        def set_top(main, **kwargs):
            main.device.image = top

        def next_page(main, page=0.5, **kwargs):
            pages.append(page)
            main.device.image = top

        with patch.object(OS_SHOP_SCROLL, 'set', side_effect=set_hint), \
                patch.object(OS_SHOP_SCROLL, 'set_top', side_effect=set_top), \
                patch.object(OS_SHOP_SCROLL, 'next_page', side_effect=next_page), \
                patch.object(shop, 'os_shop_wait_list_stable'):
            found = shop.os_shop_resolve_item_for_purchase(hint)

        self.assertIsNone(found)
        self.assertEqual(pages, [0.5, 0.5, 0.5])
        self.assertEqual(shop.device.click_record, ['previous scroll'])
        self.assertEqual(shop.device.clicks, [])


if __name__ == '__main__':
    unittest.main()
