import unittest
from datetime import datetime

from module.shipyard.auto_policy import (purchase_cost, infer_purchase_offsets,
                                        safe_purchase_amount, parse_required_level,
                                        parse_required_level_readings, server_day)


class ShipyardDailyLimitTest(unittest.TestCase):
    def test_ten_includes_two_free_and_rarities_are_independent(self):
        self.assertEqual(purchase_cost('PR', 0, 10), 3000)
        self.assertEqual(purchase_cost('DR', 0, 10), 7200)
        self.assertEqual(purchase_cost('PR', 0, 2), 0)
        self.assertEqual(purchase_cost('DR', 0, 2), 0)

    def test_live_price_recovery_after_manual_purchase_or_restart(self):
        for rarity in ('PR', 'DR'):
            for already in range(16):
                observations = [(n, purchase_cost(rarity, already, n)) for n in range(1, 7)]
                self.assertEqual(infer_purchase_offsets(rarity, observations), (already,))

    def test_no_overbuy_for_every_ambiguous_capacity_and_budget(self):
        for rarity in ('PR', 'DR'):
            for actual in range(16):
                for capacity in range(1, 7):
                    offsets = infer_purchase_offsets(rarity, [(n, purchase_cost(rarity, actual, n))
                                                             for n in range(1, capacity + 1)])
                    for coins in (0, 149, 150, 283, 600, 6283, 7200, 100000):
                        amount = safe_purchase_amount(rarity, offsets, capacity, coins)
                        self.assertLessEqual(amount, capacity)
                        self.assertLessEqual(amount, max(0, 10 - actual))
                        self.assertLessEqual(purchase_cost(rarity, actual, amount), coins)

    def test_partial_purchase_resumes_across_ships(self):
        self.assertEqual(safe_purchase_amount('DR', (0,), 10, 6283), 9)
        self.assertEqual(safe_purchase_amount('DR', (9,), 10, 283), 0)
        self.assertEqual(safe_purchase_amount('DR', (9,), 10, 1200), 1)
        self.assertEqual(safe_purchase_amount('PR', (8,), 20, 100000), 2)
        self.assertEqual(safe_purchase_amount('PR', (10,), 20, 100000), 0)

    def test_invalid_observations_never_authorize_a_purchase(self):
        self.assertEqual(infer_purchase_offsets('PR', [(1, 999)]), ())
        for offsets in ((), (-1,), (16,), (True,)):
            with self.assertRaises(ValueError):
                safe_purchase_amount('PR', offsets, 10, 10000)
        with self.assertRaises(ValueError):
            infer_purchase_offsets('DR', [(0, 0)])

    def test_server_reset_and_gate_limits(self):
        self.assertEqual(server_day(datetime(2026, 9, 16, 3, 59)), '2026-09-15')
        self.assertEqual(server_day(datetime(2026, 9, 16, 4)), '2026-09-16')
        self.assertEqual(parse_required_level('需角色到达10级'), 10)
        self.assertEqual(parse_required_level('需角色到达100级'), 100)
        for text in ('MAX', '需角色到达7级', '需角色到达11级', '需角色到达120级',
                     '开发等级10/30', '到达10级', None):
            self.assertIsNone(parse_required_level(text))

    def test_split_level_gate_readings_fail_closed(self):
        self.assertEqual(parse_required_level_readings('需角色到达', '70', '级'), 70)
        self.assertIsNone(parse_required_level_readings('', '', ''))
        for label, level, unit in (
                ('需角色到达7', '70', '级'), ('需角色到达', '7', '70级'),
                ('角色到达', 70, '级'), ('需角色到达', 0, '级'),
                ('需角色到达', '7', '级'), ('需角色到达', '11', '级'),
                ('需角色到达', '101', '级'), ('需角色到达', None, '级'),
                ('需角色到达', '70x', '级'), ('', '70', '')):
            with self.assertRaises(ValueError):
                parse_required_level_readings(label, level, unit)
