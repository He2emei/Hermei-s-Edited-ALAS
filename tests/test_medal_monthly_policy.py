import unittest

from module.shop.medal_monthly_policy import balanced_choice, confirmed_counts, priority


class TestMedalMonthlyPolicy(unittest.TestCase):
    def test_priority_order_and_protected_or_unknown_items(self):
        cases = {
            'SpecializedCore': 0,
            'BulinT2': 1,
            'BulinT1': 2,
            'DRAgirS4': 3,
            'RetrofitBBT3': 4,
            'RetrofitCLT2': 5,
            'PlateGeneralT3': 6,
            'PlateWildT1': 7,
            'BookRedT3': 8,
            'PRAnchorageS4': 9,
            'BookYellowT2': 10,
            'FoodT5': 11,
            'SpecializedCore_3': 0,
            'BookRedT3_3': 8,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(priority(name), expected)
        self.assertIsNone(priority('ShipT4'))
        self.assertIsNone(priority('ShipT4_2'))
        self.assertIsNone(priority('MysteryT3'))
        self.assertIsNone(priority('BookRedT3_99'))
        self.assertIsNone(priority('DRUnknownS4'))

    def test_balances_four_equal_choices_over_ten_units(self):
        counts = {}
        choices = ['dd', 'cl', 'bb', 'cv']
        quantities = []
        for _ in range(4):
            choice, quantity = balanced_choice(10 - sum(quantities), 10 - sum(quantities), choices, counts)
            quantities.append(quantity)
            counts[choice] = counts.get(choice, 0) + quantity
        self.assertEqual(quantities, [3, 3, 2, 2])

    def test_balances_small_budget_and_existing_gap(self):
        choices = ['dd', 'cl', 'bb', 'cv']
        counts = {}
        allocated = []
        remaining = 3
        for _ in range(4):
            choice, quantity = balanced_choice(remaining, remaining, choices, counts)
            allocated.append(quantity)
            if choice is not None:
                counts[choice] = counts.get(choice, 0) + quantity
            remaining -= quantity
        self.assertEqual(allocated, [1, 1, 1, 0])
        counts = {'dd': 0, 'cl': 2, 'bb': 2, 'cv': 2}
        self.assertEqual(balanced_choice(10, 10, ['dd', 'cl', 'bb', 'cv'], counts), ('dd', 2))

    def test_balances_white_plates_two_each(self):
        choices = ['general', 'gun', 'torpedo', 'antiair', 'plane']
        counts = {}
        allocations = []
        remaining = 10
        for _ in range(5):
            choice, quantity = balanced_choice(remaining, remaining, choices, counts)
            allocations.append(quantity)
            counts[choice] = counts.get(choice, 0) + quantity
            remaining -= quantity
        self.assertEqual(allocations, [2, 2, 2, 2, 2])

    def test_balanced_choices_reject_mixed_or_unknown_options_and_counts(self):
        for choices, counts in (
                ([], {}),
                (['dd', 'gun'], {}),
                (['dd', 'dd'], {}),
                (['mystery'], {}),
                (['dd'], {'unknown': 0}),
                (['dd'], {'dd': True}),
        ):
            with self.subTest(choices=choices, counts=counts):
                with self.assertRaises(ValueError):
                    balanced_choice(1, 1, choices, counts)

    def test_selection_choices_balance_and_priority_excludes_ssr(self):
        self.assertEqual(balanced_choice(5, 4, ['dd', 'cl'], {}), ('dd', 2))
        self.assertIsNone(priority('ShipFuture'))

    def test_rejects_bool_and_invalid_quantities_without_mutation(self):
        with self.assertRaises(ValueError):
            balanced_choice(True, 2, ['dd'], {})
        with self.assertRaises(ValueError):
            balanced_choice(2, -1, ['dd'], {})
        counts = {}
        with self.assertRaises(ValueError):
            balanced_choice(2, 2, ['dd'], {'dd': True})
        self.assertEqual(counts, {})

    def test_confirmed_counts_requires_exact_positive_currency_delta(self):
        original = {'dd': 1}
        updated = confirmed_counts(original, 'dd', 2, 200, 1000, 600)
        self.assertEqual(updated, {'dd': 3})
        self.assertEqual(original, {'dd': 1})
        for args in (
                (original, 'ShipT4', 1, 100, 1000, 900),
                (original, 'Unknown', 1, 100, 1000, 900),
                ({'cv': True}, 'dd', 1, 100, 1000, 900),
                ({'unknown': 1}, 'dd', 1, 100, 1000, 900),
                (original, 'dd', 0, 100, 1000, 1000),
                (original, 'dd', 1, 100, 1000, 800),
                (original, 'dd', True, 100, 1000, 900),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    confirmed_counts(*args)
        self.assertEqual(original, {'dd': 1})


if __name__ == '__main__':
    unittest.main()
