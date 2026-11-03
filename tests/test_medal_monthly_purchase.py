import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import RequestHumanTakeover
from module.shop.clerk import OCR_SHOP_SELECT_STOCK, ShopClerk
from module.shop.medal_monthly_ledger import MedalMonthlyLedger
from module.shop.shop_medal import MedalShop2_250814
from module.shop.shop_select_globals import SELECT_ITEM_INFO_MAP
from module.ocr.ocr import Ocr


class FakeTimer:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return self

    def reached(self):
        return False

    def reset(self):
        return self


def make_item(name='BookRedT3', group='book', tier='t3', price=20, cost='Medal'):
    return SimpleNamespace(name=name, group=group, tier=tier, price=price, cost=cost)


class TestMedalMonthlyPurchase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def _shop(self, profile='alas'):
        shop = object.__new__(MedalShop2_250814)
        shop.config = SimpleNamespace(MedalShop2_Filter='MonthlyClear', config_name=profile)
        shop._currency = 1000
        shop.device = SimpleNamespace(image=object(), screenshot=Mock(), click=Mock())
        shop._monthly_ledger = MedalMonthlyLedger(self.temp.name, profile, '2026-11')
        shop._monthly_current_item = None
        shop._monthly_before = None
        shop._monthly_receipt = None
        shop._monthly_plan = None
        return shop

    def test_default_selector_plan_and_hooks_preserve_existing_behavior(self):
        shop = object.__new__(ShopClerk)
        shop._currency = 250
        button = object()
        shop.shop_get_select = Mock(return_value=button)
        item = make_item(price=100)
        self.assertEqual(shop.shop_select_plan(item, (4, 0, 4)), (button, 2))
        shop.shop_get_select.assert_called_once_with(item)
        self.assertIsNone(ShopClerk.shop_before_select_confirm(shop, item, 1))
        self.assertIsNone(ShopClerk.shop_before_amount_confirm(shop, item, 1))
        self.assertIsNone(ShopClerk.shop_before_single_confirm(shop, item))

    def test_monthly_selector_uses_remaining_stock_and_balances_gold_families(self):
        shop = self._shop()
        shop._monthly_current_item = make_item('RetrofitBBT3', 'retrofit', 't3', 100)
        shop._monthly_before = 1000
        button, quantity = shop.shop_select_plan(shop._monthly_current_item, (4, 0, 4))
        self.assertIs(button, SELECT_ITEM_INFO_MAP['retrofit']['grid'].buttons[0])
        self.assertEqual(quantity, 1)
        self.assertEqual(shop._monthly_plan['choice'], 'dd')
        self.assertEqual(shop._monthly_plan['family'], 'RetrofitT3')

        shop._monthly_current_item = make_item('PlateWildT1', 'plate', 't1', 100)
        button, quantity = shop.shop_select_plan(shop._monthly_current_item, (4, 0, 4))
        self.assertIs(button, SELECT_ITEM_INFO_MAP['plate']['grid'].buttons[0])
        self.assertEqual(quantity, 1)
        self.assertEqual(shop._monthly_plan['family'], 'PlateT1')

    def test_non_balanced_selector_defaults_stay_general_cl_and_configured_book(self):
        shop = self._shop()
        shop._monthly_before = 500
        shop.shop_get_select = Mock(return_value=object())
        shop._monthly_current_item = make_item('PlateWildT2', 'plate', 't2', 100)
        button, quantity = shop.shop_select_plan(shop._monthly_current_item, (2, 0, 2))
        self.assertIs(button, SELECT_ITEM_INFO_MAP['plate']['grid'].buttons[0])
        self.assertEqual(quantity, 2)

        shop._monthly_current_item = make_item('RetrofitCLT2', 'retrofit', 't2', 100)
        button, quantity = shop.shop_select_plan(shop._monthly_current_item, (2, 0, 2))
        self.assertIs(button, SELECT_ITEM_INFO_MAP['retrofit']['grid'].buttons[1])
        self.assertEqual(quantity, 2)

        shop._monthly_current_item = make_item('BookRedT3', 'book', 't3', 100)
        configured_button = shop.shop_get_select.return_value
        button, quantity = shop.shop_select_plan(shop._monthly_current_item, (2, 0, 2))
        self.assertIs(button, configured_button)
        self.assertEqual(quantity, 2)

    def test_preselected_or_inconsistent_selector_never_creates_receipt(self):
        shop = self._shop()
        item = make_item('RetrofitT3', 'retrofit', 't3', 100)
        shop._monthly_current_item = item
        shop._monthly_before = 1000
        for counter in ((3, 1, 4), (2, 0, 4), (True, 0, 1)):
            with self.assertRaises(RequestHumanTakeover):
                shop.shop_select_plan(item, counter)
        self.assertIsNone(shop._monthly_ledger.load()['pending'])

    def test_real_stock_counter_parses_available_and_selected_counts(self):
        with patch.object(Ocr, 'ocr', side_effect=('4/4', '3/4')):
            self.assertEqual(OCR_SHOP_SELECT_STOCK.ocr(object()), (4, 0, 4))
            self.assertEqual(OCR_SHOP_SELECT_STOCK.ocr(object()), (3, 1, 4))

    def test_prepare_is_persisted_before_native_confirm_click(self):
        shop = self._shop()
        item = make_item(price=100)
        shop._monthly_current_item = item
        shop._monthly_before = 100
        shop.appear = Mock(return_value=True)
        shop.ui_ensure_index = Mock()
        selector = object()
        shop.shop_get_select = Mock(return_value=selector)
        shop.device.click = Mock(side_effect=lambda _button: self.assertIsNotNone(
            shop._monthly_ledger.load()['pending']))
        with patch('module.shop.clerk.Timer', FakeTimer), \
                patch('module.shop.clerk.OCR_SHOP_SELECT_STOCK.ocr',
                      side_effect=[(4, 0, 4), (3, 1, 4), (3, 1, 4)]):
            shop.shop_buy_select_execute(item)
        pending = shop._monthly_ledger.load()['pending']
        self.assertEqual(pending['quantity'], 1)
        self.assertEqual(pending['item_name'], item.name)
        shop.ui_ensure_index.assert_called_once()
        with self.assertRaises(RequestHumanTakeover):
            shop.shop_select_plan(item, (1, 0, 1))

    def test_unknown_item_cost_and_boolean_balance_are_rejected_before_receipt(self):
        shop = self._shop()
        shop._monthly_current_item = make_item('UnknownT3')
        shop._monthly_before = 100
        with self.assertRaises(RequestHumanTakeover):
            shop.shop_before_single_confirm(shop._monthly_current_item)
        self.assertIsNone(shop._monthly_ledger.load()['pending'])

        shop._monthly_current_item = make_item(cost='Gold')
        with self.assertRaises(RequestHumanTakeover):
            shop.shop_before_single_confirm(shop._monthly_current_item)
        self.assertIsNone(shop._monthly_ledger.load()['pending'])

        shop.device.screenshot = Mock()
        shop.status_get_medal = Mock(return_value=True)
        with self.assertRaises(RequestHumanTakeover):
            shop._monthly_stable_currency(allow_zero=False)

    def test_unverified_or_zero_debit_keeps_pending_and_does_not_commit(self):
        item = make_item()
        for after in (100, 79, True):
            with self.subTest(after=after):
                shop = self._shop()
                shop._monthly_stable_currency = Mock(side_effect=(100, after))

                def native_purchase(instance, target, skip_first_screenshot=True):
                    instance.shop_before_single_confirm(target)

                with patch.object(ShopClerk, 'shop_buy_execute', native_purchase):
                    with self.assertRaises(RequestHumanTakeover):
                        shop.shop_buy_execute(item)
                pending = shop._monthly_ledger.load()['pending']
                self.assertIsNotNone(pending)
                self.assertEqual(shop._monthly_ledger.load()['history'], [])

    def test_profile_ledgers_remain_separate_after_confirmed_purchase(self):
        for profile in ('alas', 'alas2'):
            shop = self._shop(profile)
            shop._monthly_stable_currency = Mock(side_effect=(100, 80))

            def native_purchase(instance, target, skip_first_screenshot=True):
                instance.shop_before_single_confirm(target)

            with patch.object(ShopClerk, 'shop_buy_execute', native_purchase):
                shop.shop_buy_execute(make_item())

        alas = MedalMonthlyLedger(self.temp.name, 'alas', '2026-11').load()
        alas2 = MedalMonthlyLedger(self.temp.name, 'alas2', '2026-11').load()
        self.assertEqual(len(alas['history']), 1)
        self.assertEqual(len(alas2['history']), 1)
        self.assertNotEqual(alas['history'][0]['txid'], alas2['history'][0]['txid'])


if __name__ == '__main__':
    unittest.main()
