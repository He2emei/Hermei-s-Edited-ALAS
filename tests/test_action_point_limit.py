import unittest
from datetime import date

from module.os_handler.action_point_limit import ActionPointLimitPolicy


MANUAL_AT = 'OpsiGeneral.Storage.Storage.BuyActionPointLimitManualAt'


class FakeConfig:
    def __init__(self, gui_limit, manual_at=None):
        self.OpsiGeneral_BuyActionPointLimit = gui_limit
        self.values = {}
        if manual_at is not None:
            self.values[MANUAL_AT] = manual_at
        self.set_calls = []

    def cross_get(self, keys, default=None):
        return self.values.get(keys, default)

    def cross_set(self, keys, value):
        self.values[keys] = value
        self.set_calls.append((keys, value))


class ActionPointLimitPolicyTest(unittest.TestCase):
    def make_policy(self, gui_limit, manual_at=None):
        policy = ActionPointLimitPolicy()
        policy.config = FakeConfig(gui_limit, manual_at)
        return policy

    def test_manual_gui_value_wins_for_the_current_week(self):
        policy = self.make_policy(5, '2026-07-15 08:00:00')

        actual = policy.get_buy_action_point_limit(today=date(2026, 7, 15))
        later = policy.get_buy_action_point_limit(today=date(2026, 7, 19))

        self.assertEqual(actual, 5)
        self.assertEqual(later, 5)
        self.assertEqual(policy.config.OpsiGeneral_BuyActionPointLimit, 5)

    def test_next_week_restores_automatic_value_and_syncs_gui(self):
        policy = self.make_policy(5, '2026-07-15 08:00:00')

        actual = policy.get_buy_action_point_limit(today=date(2026, 7, 20))

        self.assertEqual(actual, 0)
        self.assertEqual(policy.config.OpsiGeneral_BuyActionPointLimit, 0)

    def test_existing_gui_value_is_kept_for_migration_week(self):
        policy = self.make_policy(5)

        actual = policy.get_buy_action_point_limit(today=date(2026, 7, 15))

        self.assertEqual(actual, 5)
        self.assertEqual(policy.config.OpsiGeneral_BuyActionPointLimit, 5)
        self.assertEqual(len(policy.config.set_calls), 1)
        self.assertEqual(policy.config.set_calls[0][0], MANUAL_AT)

    def test_first_run_after_migration_week_uses_automatic_value(self):
        policy = self.make_policy(5)

        actual = policy.get_buy_action_point_limit(today=date(2026, 7, 20))

        self.assertEqual(actual, 0)
        self.assertEqual(policy.config.OpsiGeneral_BuyActionPointLimit, 0)
        self.assertEqual(policy.config.set_calls, [])

    def test_automatic_rule_uses_five_during_first_two_calendar_weeks(self):
        policy = self.make_policy(0, '2026-06-01 08:00:00')

        actual = policy.get_buy_action_point_limit(today=date(2026, 7, 6))

        self.assertEqual(actual, 5)
        self.assertEqual(policy.config.OpsiGeneral_BuyActionPointLimit, 5)


if __name__ == '__main__':
    unittest.main()
