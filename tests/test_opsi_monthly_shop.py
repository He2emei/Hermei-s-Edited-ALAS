import unittest
from datetime import datetime
from types import SimpleNamespace

from module.os.tasks.cross_month import OpsiCrossMonth, monthly_shop_clearout_start
from module.os.tasks.shop import OpsiShop as OpsiShopTask
from module.os_shop.selector import Selector
from module.os_shop.shop import OSShop


def shop_item(name, shop_index, count=1, total_count=1):
    return SimpleNamespace(
        name=name,
        shop_index=shop_index,
        count=count,
        total_count=total_count,
    )


class MonthlyShopSelectorTest(unittest.TestCase):
    def test_applies_a_different_clearout_rule_to_each_port(self):
        items = [
            shop_item('LoggerAbyssalT6', 0),
            shop_item('ActionPoint100', 0),
            shop_item('PurpleCoins', 0),
            shop_item('PurpleCoins', 1),
            shop_item('RepairPackFull', 1),
            shop_item('GearDesignPlanT3', 1),
            shop_item('PurpleCoins', 2),
            shop_item('RepairPackTriple2', 2),
            shop_item('EnergyStorageDevice', 2),
            shop_item('RepairPack', 3),
            shop_item('RepairPackFull2', 3),
            shop_item('LoggerObscureT4', 3),
            shop_item('TuningSampleCombat', 3),
        ]

        selected = Selector().items_filter_in_monthly_clearout(items)

        self.assertEqual(
            [(item.shop_index, item.name) for item in selected],
            [
                (0, 'LoggerAbyssalT6'),
                (1, 'RepairPackFull'),
                (1, 'GearDesignPlanT3'),
                (2, 'PurpleCoins'),
                (2, 'RepairPackTriple2'),
                (2, 'EnergyStorageDevice'),
                (3, 'LoggerObscureT4'),
                (3, 'TuningSampleCombat'),
            ],
        )

    def test_ignores_unknown_items_and_invalid_counters(self):
        selected = Selector().items_filter_in_monthly_clearout([
            shop_item('UnknownFutureItem', 2),
            shop_item('LoggerAbyssalT6', 0, count=0),
            shop_item('LoggerObscureT4', 0, count=2, total_count=1),
            shop_item('LoggerObscureT5', 0),
        ])

        self.assertEqual([item.name for item in selected], ['LoggerObscureT5'])


class MonthlyBuyHarness:
    _handle_port_supply_buy = OSShop._handle_port_supply_buy
    handle_monthly_port_supply_buy = OSShop.handle_monthly_port_supply_buy

    def __init__(self, items):
        self.items = items

    def scan_all(self):
        return self.items

    def items_filter_in_monthly_clearout(self, items):
        return Selector().items_filter_in_monthly_clearout(items)


class MonthlyShopRetryTest(unittest.TestCase):
    @staticmethod
    def handle(items):
        return MonthlyBuyHarness(items).handle_monthly_port_supply_buy()

    def test_empty_scan_is_retried(self):
        self.assertTrue(self.handle([]))

    def test_unknown_item_is_retried(self):
        self.assertTrue(self.handle([shop_item('UnknownFutureItem', 2)]))

    def test_invalid_counter_is_retried(self):
        self.assertTrue(self.handle([shop_item('LoggerAbyssalT6', 0, count=0, total_count=0)]))

    def test_sold_out_target_is_reliably_ignored(self):
        self.assertFalse(self.handle([shop_item('LoggerAbyssalT6', 0, count=0, total_count=1)]))

    def test_missing_shop_page_is_retried(self):
        campaign = SimpleNamespace(_os_shop_visit=lambda monthly_clearout: None)
        self.assertTrue(OpsiShopTask.os_shop_monthly_clearout(campaign))


class FakeConfig:
    def __init__(self):
        self.task_delays = []
        self.task_stops = 0

    def task_delay(self, **kwargs):
        self.task_delays.append(kwargs)

    def task_stop(self):
        self.task_stops += 1


class CrossMonthHarness:
    def __init__(self, shop_pending=False):
        self.config = FakeConfig()
        self.shop_pending = shop_pending
        self.shop_calls = 0

    def os_shop_monthly_clearout(self):
        self.shop_calls += 1
        return self.shop_pending


class MonthlyShopSchedulingTest(unittest.TestCase):
    RESET = datetime(2026, 9, 1, 0, 0)

    def prepare(self, now, pending=False):
        campaign = CrossMonthHarness(shop_pending=pending)
        handled = OpsiCrossMonth._prepare_monthly_shop(campaign, self.RESET, now)
        return campaign, handled

    def test_clearout_window_starts_three_days_before_monthly_reset(self):
        self.assertEqual(
            monthly_shop_clearout_start(self.RESET),
            datetime(2026, 8, 29, 0, 0),
        )

    def test_before_window_schedules_the_window_start_without_visiting_shop(self):
        campaign, handled = self.prepare(datetime(2026, 8, 27, 12, 0))

        self.assertTrue(handled)
        self.assertEqual(campaign.shop_calls, 0)
        self.assertEqual(campaign.config.task_delays, [{'target': datetime(2026, 8, 29, 0, 0)}])
        self.assertEqual(campaign.config.task_stops, 1)

    def test_missed_window_start_runs_clearout_when_program_resumes(self):
        campaign, handled = self.prepare(datetime(2026, 8, 30, 7, 15), pending=True)

        self.assertTrue(handled)
        self.assertEqual(campaign.shop_calls, 1)
        self.assertEqual(campaign.config.task_delays, [{'target': datetime(2026, 8, 30, 13, 15)}])

    def test_pending_items_retry_every_six_hours_but_not_past_cross_month_wait(self):
        campaign, _ = self.prepare(datetime(2026, 8, 31, 20, 0), pending=True)

        self.assertEqual(campaign.config.task_delays, [{'target': datetime(2026, 8, 31, 23, 50)}])

    def test_cleared_shop_waits_until_existing_cross_month_flow(self):
        campaign, handled = self.prepare(datetime(2026, 8, 29, 2, 0), pending=False)

        self.assertTrue(handled)
        self.assertEqual(campaign.shop_calls, 1)
        self.assertEqual(campaign.config.task_delays, [{'target': datetime(2026, 8, 31, 23, 50)}])

    def test_final_ten_minutes_are_reserved_for_existing_cross_month_flow(self):
        campaign, handled = self.prepare(datetime(2026, 8, 31, 23, 55), pending=True)

        self.assertFalse(handled)
        self.assertEqual(campaign.shop_calls, 0)
        self.assertEqual(campaign.config.task_delays, [])
        self.assertEqual(campaign.config.task_stops, 0)


if __name__ == '__main__':
    unittest.main()
