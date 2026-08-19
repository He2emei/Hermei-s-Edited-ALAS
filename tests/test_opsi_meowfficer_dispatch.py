import unittest
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

from module.campaign.os_run import OSCampaignRun
from module.os.task_dispatch import (
    OPSI_MEOWFFICER_FALLBACK_TASK,
    OPSI_MEOWFFICER_PRIORITY_TASKS,
    run_first_available,
)
from module.os.tasks.meowfficer_farming_priority import OpsiMeowfficerFarmingPriority
from module.os.tasks.stronghold import OpsiStronghold
from module.os_handler.action_point import ActionPointLimit


class FakeConfig:
    OpsiHazard1Leveling_YellowCoinsPreserve = 10000

    def __init__(self, enabled_tasks=()):
        self.enabled_tasks = set(enabled_tasks)
        self.bind_calls = []
        self.task_calls = []
        self.task_delays = []
        self.cross_sets = []
        self.task = SimpleNamespace(command='TestTask')

    def is_task_enabled(self, task):
        return task in self.enabled_tasks

    def cross_get(self, key, default):
        return default

    def cross_set(self, keys, value):
        self.cross_sets.append((keys, value))

    def bind(self, task):
        self.bind_calls.append(task)

    def task_delay(self, **kwargs):
        self.task_delays.append(kwargs)

    def task_call(self, task):
        self.task_calls.append(task)

    def multi_set(self):
        return nullcontext()


class PriorityCampaignHarness(OpsiMeowfficerFarmingPriority):
    def __init__(
            self, config, availability, action_points=5000, yellow_coins=20000,
            yellow_coins_after_run=None, in_explore=False, cooling_down=None):
        self.config = config
        self.availability = availability
        self.action_points = action_points
        self.yellow_coins = yellow_coins
        self.yellow_coins_after_run = yellow_coins_after_run or {}
        self.in_explore = in_explore
        self.cooling_down = cooling_down
        self.run_calls = []

    def is_in_opsi_explore(self):
        return self.in_explore

    @property
    def nearest_task_cooling_down(self):
        return self.cooling_down

    def try_clear_stronghold(self):
        return self._try_clear('OpsiStronghold')

    def try_clear_abyssal(self):
        return self._try_clear('OpsiAbyssal')

    def try_clear_obscure(self):
        return self._try_clear('OpsiObscure')

    def os_meowfficer_farming(self):
        self.run_calls.append('OpsiMeowfficerFarming')

    def get_cl1_meowfficer_threshold(self):
        return 4500

    def action_point_check(self, amount):
        self._action_point_total = self.action_points
        return self.action_points > amount

    def get_yellow_coins(self):
        return self.yellow_coins

    def _try_clear(self, task):
        self.run_calls.append(task)
        available = self.availability[task]
        if isinstance(available, BaseException):
            raise available
        if available and task in self.yellow_coins_after_run:
            self.yellow_coins = self.yellow_coins_after_run[task]
        return available


class CandidateTransitionHarness(PriorityCampaignHarness):
    def __init__(self, config):
        super().__init__(config, {}, action_points=5000)
        self.current_page = 'map'
        self.map_restore_calls = 0

    def try_clear_stronghold(self):
        self.run_calls.append('OpsiStronghold')
        return OpsiStronghold.try_clear_stronghold(self)

    def cl1_ap_preserve(self):
        pass

    def os_map_goto_globe(self):
        self.current_page = 'globe'

    def globe_update(self):
        pass

    def find_siren_stronghold(self):
        return None

    def os_globe_goto_map(self):
        self.map_restore_calls += 1
        self.current_page = 'map'

    def try_clear_abyssal(self):
        self.run_calls.append('OpsiAbyssal')
        if self.current_page != 'map':
            raise AssertionError('Abyssal started before the failed stronghold probe restored the OS map')
        return True


class OpsiMeowfficerDispatchTest(unittest.TestCase):
    def test_failed_stronghold_probe_restores_map_before_abyssal_candidate(self):
        config = FakeConfig()
        campaign = CandidateTransitionHarness(config)

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiAbyssal')
        self.assertEqual(
            config.bind_calls,
            ['OpsiStronghold', 'OpsiAbyssal', 'OpsiMeowfficerFarming'],
        )
        self.assertEqual(campaign.run_calls, ['OpsiStronghold', 'OpsiAbyssal'])
        self.assertEqual(campaign.map_restore_calls, 1)
        self.assertEqual(campaign.current_page, 'map')

    def test_cooling_down_task_delays_without_bypassing_policy_into_shortcat(self):
        config = FakeConfig(enabled_tasks={'OpsiHazard1Leveling'})
        next_run = datetime(2026, 8, 19, 13, 30)
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': True,
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        }, cooling_down=SimpleNamespace(next_run=next_run))

        result = campaign.os_meowfficer_farming_priority()

        self.assertIsNone(result)
        self.assertEqual(campaign.run_calls, [])
        self.assertEqual(config.task_delays, [{'target': next_run}])

    def test_explore_block_delays_without_bypassing_policy_into_shortcat(self):
        config = FakeConfig()
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': True,
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        }, in_explore=True)

        result = campaign.os_meowfficer_farming_priority()

        self.assertIsNone(result)
        self.assertEqual(campaign.run_calls, [])
        self.assertEqual(config.task_delays, [{'server_update': True}])

    def test_exact_action_point_threshold_allows_shortcat_fallback(self):
        config = FakeConfig()
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': False,
            'OpsiAbyssal': False,
            'OpsiObscure': False,
        }, action_points=4500)

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiMeowfficerFarming')
        self.assertEqual(campaign.run_calls, [
            'OpsiStronghold',
            'OpsiAbyssal',
            'OpsiObscure',
            'OpsiMeowfficerFarming',
        ])

    def test_action_point_limited_candidate_falls_through_to_next_high_value_map(self):
        config = FakeConfig()
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': ActionPointLimit(),
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        })

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiAbyssal')
        self.assertEqual(campaign.run_calls, ['OpsiStronghold', 'OpsiAbyssal'])

    def test_high_value_standalone_entries_route_through_unified_dispatch_in_hazard1_mode(self):
        for entry in ('opsi_stronghold', 'opsi_abyssal', 'opsi_obscure'):
            with self.subTest(entry=entry):
                config = FakeConfig()
                config.OpsiMeowfficerFarming_OperatingMode = 'hazard1_mode'
                task = {
                    'opsi_stronghold': 'OpsiStronghold',
                    'opsi_abyssal': 'OpsiAbyssal',
                    'opsi_obscure': 'OpsiObscure',
                }[entry]
                config.task.command = task
                runner = object.__new__(OSCampaignRun)
                runner.config = config
                runner.load_campaign = lambda: self.fail(f'{entry} bypassed unified dispatch')

                getattr(runner, entry)()

                self.assertEqual(config.task_calls, ['OpsiMeowfficerFarming'])
                self.assertEqual(config.task_delays, [{'success': True}])
                self.assertEqual(config.cross_sets, [(f'{task}.Scheduler.Enable', False)])

    def test_high_value_map_rechecks_the_same_policy_while_cl1_fuel_is_still_low(self):
        config = FakeConfig(enabled_tasks={'OpsiHazard1Leveling'})
        campaign = PriorityCampaignHarness(
            config,
            {
                'OpsiStronghold': True,
                'OpsiAbyssal': True,
                'OpsiObscure': True,
            },
            action_points=4499,
            yellow_coins=9000,
            yellow_coins_after_run={'OpsiStronghold': 9500},
        )

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiStronghold')
        self.assertEqual(config.task_calls, ['OpsiMeowfficerFarming'])

    def test_high_value_map_refill_resumes_cl1_as_soon_as_fuel_is_restored(self):
        config = FakeConfig(enabled_tasks={'OpsiHazard1Leveling'})
        campaign = PriorityCampaignHarness(
            config,
            {
                'OpsiStronghold': True,
                'OpsiAbyssal': True,
                'OpsiObscure': True,
            },
            action_points=4499,
            yellow_coins=9000,
            yellow_coins_after_run={'OpsiStronghold': 12000},
        )

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiStronghold')
        self.assertEqual(campaign.run_calls, ['OpsiStronghold'])
        self.assertEqual(config.task_calls, ['OpsiHazard1Leveling'])

    def test_low_action_points_and_unavailable_cl1_never_fall_back_to_shortcat(self):
        config = FakeConfig(enabled_tasks={'OpsiHazard1Leveling'})
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': False,
            'OpsiAbyssal': False,
            'OpsiObscure': False,
        }, action_points=4499, yellow_coins=10000)

        result = campaign.os_meowfficer_farming_priority()

        self.assertIsNone(result)
        self.assertEqual(campaign.run_calls, [
            'OpsiStronghold',
            'OpsiAbyssal',
            'OpsiObscure',
        ])
        self.assertNotIn('OpsiMeowfficerFarming', campaign.run_calls)
        self.assertEqual(config.task_delays, [{'success': False}])

    def test_low_action_points_and_available_cl1_resume_hazard1_without_spending_high_value_maps(self):
        config = FakeConfig(enabled_tasks={'OpsiHazard1Leveling'})
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': True,
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        }, action_points=4499, yellow_coins=10001)

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiHazard1Leveling')
        self.assertEqual(campaign.run_calls, [])
        self.assertEqual(config.task_calls, ['OpsiHazard1Leveling'])

    def test_unified_dispatch_considers_high_value_tasks_with_standalone_schedulers_disabled(self):
        config = FakeConfig()
        campaign = PriorityCampaignHarness(config, {
            'OpsiStronghold': True,
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        })

        result = campaign.os_meowfficer_farming_priority()

        self.assertEqual(result, 'OpsiStronghold')
        self.assertEqual(campaign.run_calls, ['OpsiStronghold'])

    def test_runs_only_the_highest_priority_available_task(self):
        config = FakeConfig(
            enabled_tasks={'OpsiStronghold', 'OpsiAbyssal', 'OpsiObscure'},
        )
        checks = []

        def check(task, available):
            def run():
                checks.append(task)
                return available
            return run

        fallback_calls = []
        availability = {
            'OpsiStronghold': False,
            'OpsiAbyssal': True,
            'OpsiObscure': True,
        }
        candidates = [
            (task, check(task, availability[task]))
            for task, _ in OPSI_MEOWFFICER_PRIORITY_TASKS
        ]

        result = run_first_available(
            config,
            candidates,
            (OPSI_MEOWFFICER_FALLBACK_TASK, lambda: fallback_calls.append(True)),
        )

        self.assertEqual(result, 'OpsiAbyssal')
        self.assertEqual(checks, ['OpsiStronghold', 'OpsiAbyssal'])
        self.assertEqual(config.bind_calls, ['OpsiStronghold', 'OpsiAbyssal'])
        self.assertEqual(fallback_calls, [])

    def test_standalone_scheduler_flags_do_not_filter_unavailable_candidates(self):
        config = FakeConfig(enabled_tasks={'OpsiAbyssal', 'OpsiObscure'})
        checks = []
        fallback_calls = []

        result = run_first_available(
            config,
            [
                (task, lambda task=task: checks.append(task) or False)
                for task, _ in OPSI_MEOWFFICER_PRIORITY_TASKS
            ],
            (OPSI_MEOWFFICER_FALLBACK_TASK, lambda: fallback_calls.append(True)),
        )

        self.assertEqual(result, 'OpsiMeowfficerFarming')
        self.assertEqual(checks, ['OpsiStronghold', 'OpsiAbyssal', 'OpsiObscure'])
        self.assertEqual(
            config.bind_calls,
            ['OpsiStronghold', 'OpsiAbyssal', 'OpsiObscure', 'OpsiMeowfficerFarming'],
        )
        self.assertEqual(fallback_calls, [True])


if __name__ == '__main__':
    unittest.main()
