import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.shop.base import ShopBase
from module.shop.shop_medal import MedalShop2_250814
from module.shop.medal_monthly_ledger import MedalMonthlyLedger


class FakeShopScroll:
    drag_threshold = 0.1
    edge_threshold = 0.12

    def __init__(self, last_page):
        self.last_page = last_page
        self.page = 0
        self.drag_threshold = min(0.1, 0.5 / max(last_page, 1))

    def cal_position(self, main):
        return self.page / max(self.last_page, 1)

    def set_top(self, main):
        self.page = 0

    def at_top(self, main):
        return self.page == 0

    def at_bottom(self, main):
        return self.page >= self.last_page

    def next_page(self, main, page=0.66):
        self.page = min(self.page + 1, self.last_page)


def item(name, cost='Medal', price=100):
    return SimpleNamespace(name=name, cost=cost, price=price)


def shop_instance(filter_value='MonthlyClear'):
    shop = MedalShop2_250814.__new__(MedalShop2_250814)
    shop.config = SimpleNamespace(MedalShop2_Filter=filter_value, config_name='alas')
    shop.device = SimpleNamespace(click_record_clear=Mock())
    shop._currency = 10000
    return shop


class TestMedalMonthlyRoute(unittest.TestCase):
    def _isolated_ledger(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return patch('module.shop.shop_medal.MedalMonthlyLedger',
                     side_effect=lambda _root, profile: MedalMonthlyLedger(temp.name, profile, '2026-11'))

    def run_with_pages(self, pages, balance=10000, last_page=None, max_pages=None):
        if last_page is None:
            last_page = len(pages) - 1
        shop = shop_instance()
        pages = [list(page) for page in pages]
        balance_box = [balance]
        purchases = []

        def fake_buy():
            while True:
                shop._currency = balance_box[0]
                target = shop.shop_get_item_to_buy(pages[scroll.page])
                if target is None:
                    return True
                purchases.append(target.name)
                pages[scroll.page].remove(target)
                balance_box[0] -= int(target.price)

        scroll = FakeShopScroll(last_page)
        shop.shop_buy = fake_buy
        if max_pages is not None:
            shop.MONTHLY_CLEAR_MAX_PAGES_PER_RANK = max_pages
        with self._isolated_ledger(), \
                patch('module.shop.shop_medal.MEDAL_SHOP_SCROLL_250814', scroll), \
                patch('time.sleep'):
            shop.run()
        return shop, purchases, scroll

    def test_scans_later_pages_for_higher_priority_and_skips_ssr_and_unknown(self):
        pages = [
            [item('BulinT2'), item('ShipT4'), item('ShipT4_2'), item('UnknownT3')],
            [item('SpecializedCore')],
        ]
        _, purchases, _ = self.run_with_pages(pages)
        self.assertEqual(purchases, ['SpecializedCore', 'BulinT2'])

    def test_unreadable_cost_or_price_is_rejected(self):
        shop = shop_instance()
        shop._monthly_clear_active_rank = 1
        shop._monthly_clear_metadata_blocked = False
        shop._currency = 1000
        self.assertIsNone(shop.shop_get_item_to_buy([item('BulinT2', cost='DefaultCost')]))
        self.assertTrue(shop._monthly_clear_metadata_blocked)

        shop._monthly_clear_metadata_blocked = False
        self.assertIsNone(shop.shop_get_item_to_buy([item('BulinT2', price='100')]))
        self.assertTrue(shop._monthly_clear_metadata_blocked)
        self.assertIsNone(shop.shop_get_item_to_buy([item('ShipT4')]))
        self.assertFalse(shop.shop_check_custom_item(item('ShipT4')))

    def test_insufficient_higher_rank_item_blocks_lower_rank_purchase(self):
        pages = [
            [item('SpecializedCore', price=np.int64(200))],
            [item('BulinT2', price=20)],
        ]
        _, purchases, _ = self.run_with_pages(pages, balance=100)
        self.assertEqual(purchases, [])

    def test_non_monthly_filter_delegates_to_existing_selector(self):
        shop = shop_instance('BulinT2')
        target = item('BulinT2')
        with patch.object(ShopBase, 'shop_get_item_to_buy', return_value=target) as base_selector:
            self.assertIs(shop.shop_get_item_to_buy([target]), target)
        base_selector.assert_called_once_with([target])

    def test_page_scan_is_bounded_and_stops_on_unmeasured_progress(self):
        pages = [[] for _ in range(20)]
        _, _, scroll = self.run_with_pages(pages, last_page=19, max_pages=3)
        self.assertEqual(scroll.page, 2)

        shop = shop_instance()
        shop._monthly_clear_active_rank = None
        shop.shop_buy = Mock(return_value=True)
        stalled_scroll = FakeShopScroll(last_page=5)
        stalled_scroll.next_page = lambda main, page=0.66: None
        with self._isolated_ledger(), \
                patch('module.shop.shop_medal.MEDAL_SHOP_SCROLL_250814', stalled_scroll), \
                patch('time.sleep'):
            shop.run()
        shop.shop_buy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
