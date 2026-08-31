import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from module.campaign.os_run import OSCampaignRun
from module.exception import ScriptError
from module.os.tasks.cross_month import (
    OpsiCrossMonth,
    is_cross_month_catch_up,
    monthly_shop_clearout_start,
)
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

    def test_large_action_point_boxes_are_reserved_for_cross_month(self):
        items = [
            shop_item('ActionPoint20', 1),
            shop_item('ActionPoint50', 1),
            shop_item('ActionPoint100', 1),
        ]

        month_end = Selector().items_filter_in_monthly_clearout(items)
        cross_month = Selector().items_filter_in_cross_month(items)

        self.assertEqual(
            [item.name for item in month_end],
            ['ActionPoint20', 'ActionPoint50'],
        )
        self.assertEqual(
            [item.name for item in cross_month],
            ['ActionPoint100'],
        )

    def test_regular_shop_does_not_buy_reserved_large_boxes(self):
        selector = Selector()
        selector.config = SimpleNamespace(
            OpsiShop_PresetFilter='all',
            OpsiShop_CustomFilter='',
        )
        selector.is_cl1_enabled = False
        items = [
            shop_item('ActionPoint20', 1),
            shop_item('ActionPoint50', 1),
            shop_item('ActionPoint100', 1),
        ]

        selected = selector.items_filter_in_os_shop(items)

        self.assertEqual(
            [item.name for item in selected],
            ['ActionPoint20', 'ActionPoint50'],
        )


class MonthlyBuyHarness(OSShop):
    def __init__(self, items):
        self.items = items

    def scan_all(self):
        return self.items

    def items_filter_in_monthly_clearout(self, items):
        return Selector().items_filter_in_monthly_clearout(items)


class MonthlyCoinReserveHarness(OSShop):
    def __init__(self, yellow_coins):
        self._shop_yellow_coins = yellow_coins
        self._shop_purple_coins = 0

    def items_filter_in_monthly_clearout(self, items):
        return items

    def items_filter_in_cross_month(self, items):
        return items

    def _handle_port_supply_buy(self, **kwargs):
        item = SimpleNamespace(cost='YellowCoins')
        return self.get_currency_coins(item)


class MonthlyShopCoinReserveTest(unittest.TestCase):
    def test_month_end_reserves_twenty_thousand_yellow_coins(self):
        campaign = MonthlyCoinReserveHarness(yellow_coins=25000)

        available = campaign.handle_monthly_port_supply_buy()

        self.assertEqual(available, 5000)

    def test_cross_month_releases_reserved_coins_for_large_boxes(self):
        campaign = MonthlyCoinReserveHarness(yellow_coins=25000)

        available = campaign.handle_cross_month_port_supply_buy()

        self.assertEqual(available, 25000)

    def test_regular_shop_keeps_cross_month_reserve_on_last_day(self):
        campaign = MonthlyCoinReserveHarness(yellow_coins=25000)
        campaign.config = SimpleNamespace(
            is_task_enabled=lambda task: task == 'OpsiCrossMonth',
        )
        item = SimpleNamespace(cost='YellowCoins')

        with patch('module.os_shop.shop.get_os_reset_remain', return_value=0):
            available = campaign.get_currency_coins(item)

        self.assertEqual(available, 5000)


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

    def test_overdue_cross_month_task_is_caught_up_after_reset(self):
        self.assertTrue(is_cross_month_catch_up(
            scheduled=datetime(2026, 8, 31, 23, 50),
            now=datetime(2026, 9, 1, 0, 1),
        ))

    def test_old_unrelated_schedule_does_not_trigger_cross_month_catch_up(self):
        self.assertFalse(is_cross_month_catch_up(
            scheduled=datetime(2020, 1, 1, 0, 0),
            now=datetime(2026, 9, 1, 0, 1),
        ))

    def test_failed_large_box_purchase_blocks_old_world_refresh(self):
        class Campaign:
            def __init__(self):
                self.shop_calls = 0

            def os_shop_cross_month_action_points(self):
                self.shop_calls += 1
                return True

        campaign = Campaign()
        with self.assertRaisesRegex(ScriptError, 'refusing to leave'):
            OpsiCrossMonth._buy_cross_month_action_points(campaign)
        self.assertEqual(campaign.shop_calls, 3)

    def test_reset_buys_reserved_boxes_before_other_old_world_work(self):
        class PurchaseObserved(Exception):
            pass

        class Device:
            def sleep(self, seconds):
                raise AssertionError(f'Unexpected sleep: {seconds}')

        class Campaign:
            config = FakeConfig()
            device = Device()
            _prepare_monthly_shop = OpsiCrossMonth._prepare_monthly_shop
            _buy_cross_month_action_points = OpsiCrossMonth._buy_cross_month_action_points

            def __init__(self):
                self.shop_calls = 0

            def os_shop_cross_month_action_points(self):
                self.shop_calls += 1
                if self.shop_calls == 1:
                    return True
                raise PurchaseObserved

        campaign = Campaign()
        with patch('module.os.tasks.cross_month.get_os_next_reset', return_value=self.RESET), \
                patch('module.os.tasks.cross_month.datetime') as mocked_datetime:
            mocked_datetime.now.side_effect = [
                datetime(2026, 8, 31, 23, 55),
                self.RESET,
            ]
            with self.assertRaises(PurchaseObserved):
                OpsiCrossMonth.os_cross_month(campaign)
        self.assertEqual(campaign.shop_calls, 2)


class CrossMonthCatchUpRunnerTest(unittest.TestCase):
    NOW = datetime(2026, 9, 1, 0, 1)
    SCHEDULED = datetime(2026, 8, 31, 23, 50)

    class Device:
        def __init__(self):
            self.screenshots = 0

        def screenshot(self):
            self.screenshots += 1

    class Campaign:
        def __init__(self):
            self.catch_up = None

        def os_cross_month(self, catch_up=False):
            self.catch_up = catch_up

    class Runner:
        opsi_cross_month = OSCampaignRun.opsi_cross_month

        def __init__(self, in_map):
            self.config = FakeConfig()
            self.config.task = SimpleNamespace(
                next_run=CrossMonthCatchUpRunnerTest.SCHEDULED,
            )
            self.device = CrossMonthCatchUpRunnerTest.Device()
            self.in_map = in_map
            self.campaign = CrossMonthCatchUpRunnerTest.Campaign()
            self.load_calls = 0
            self.skip_first_auto_search = None

        def is_in_map(self):
            return self.in_map

        def is_in_globe(self):
            return False

        def load_campaign(self, skip_first_auto_search=False):
            self.load_calls += 1
            self.skip_first_auto_search = skip_first_auto_search
            return self.campaign

    def test_overdue_run_stays_in_old_world_and_enters_catch_up_flow(self):
        runner = self.Runner(in_map=True)

        with patch('module.campaign.os_run.datetime') as mocked_datetime:
            mocked_datetime.now.return_value = self.NOW
            runner.opsi_cross_month()

        self.assertEqual(runner.device.screenshots, 1)
        self.assertEqual(runner.load_calls, 1)
        self.assertTrue(runner.skip_first_auto_search)
        self.assertTrue(runner.campaign.catch_up)

    def test_overdue_run_outside_opsi_skips_lost_old_world_and_reschedules(self):
        runner = self.Runner(in_map=False)

        with patch('module.campaign.os_run.datetime') as mocked_datetime, \
                patch(
                    'module.campaign.os_run.get_os_next_reset',
                    return_value=datetime(2026, 10, 1, 0, 0),
                    create=True,
                ):
            mocked_datetime.now.return_value = self.NOW
            runner.opsi_cross_month()

        self.assertEqual(runner.load_calls, 0)
        self.assertEqual(
            runner.config.task_delays,
            [{'target': datetime(2026, 9, 28, 0, 0)}],
        )
        self.assertEqual(runner.config.task_stops, 1)


if __name__ == '__main__':
    unittest.main()
