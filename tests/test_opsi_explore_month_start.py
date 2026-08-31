import unittest

from module.campaign.os_run import OSCampaignRun
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


class OpsiDailyExploreGuardTest(unittest.TestCase):
    class Config:
        def __init__(self):
            self.delay_calls = []
            self.stop_calls = 0

        def task_delay(self, **kwargs):
            self.delay_calls.append(kwargs)

        def task_stop(self):
            self.stop_calls += 1

    class Runner:
        opsi_daily = OSCampaignRun.opsi_daily

        def __init__(self):
            self.config = OpsiDailyExploreGuardTest.Config()
            self.load_calls = 0

        def is_in_opsi_explore(self):
            return True

        def load_campaign(self):
            self.load_calls += 1
            raise AssertionError('OpsiDaily entered Operation Siren during OpsiExplore')

    def test_daily_is_delayed_without_entering_opsi_while_explore_is_running(self):
        runner = self.Runner()

        runner.opsi_daily()

        self.assertEqual(runner.load_calls, 0)
        self.assertEqual(runner.config.delay_calls, [{'server_update': True}])
        self.assertEqual(runner.config.stop_calls, 1)


if __name__ == '__main__':
    unittest.main()
