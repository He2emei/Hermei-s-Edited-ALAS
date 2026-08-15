import unittest

from module.os.tasks.explore import OpsiExplore


class FakeConfig:
    def __init__(self, obscure_enabled):
        self.values = {
            'OpsiObscure.Scheduler.Enable': obscure_enabled,
        }
        self.set_calls = []

    def cross_get(self, keys, default=None):
        return self.values.get(keys, default)

    def cross_set(self, keys, value):
        self.values[keys] = value
        self.set_calls.append((keys, value))


class OpsiExploreMonthStartTest(unittest.TestCase):
    def make_explore(self, obscure_enabled=True):
        explore = object.__new__(OpsiExplore)
        explore.config = FakeConfig(obscure_enabled)
        return explore

    def test_month_start_disables_obscure_task(self):
        explore = self.make_explore(obscure_enabled=True)

        explore._disable_obscure_at_month_start()

        self.assertEqual(
            explore.config.set_calls,
            [('OpsiObscure.Scheduler.Enable', False)],
        )

    def test_month_start_leaves_disabled_obscure_task_unchanged(self):
        explore = self.make_explore(obscure_enabled=False)

        explore._disable_obscure_at_month_start()

        self.assertEqual(explore.config.set_calls, [])


if __name__ == '__main__':
    unittest.main()
