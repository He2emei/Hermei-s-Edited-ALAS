import unittest

from module.os.task_dispatch import (
    OPSI_MEOWFFICER_FALLBACK_TASK,
    OPSI_MEOWFFICER_PRIORITY_TASKS,
    run_first_available,
)


class FakeConfig:
    def __init__(self, enabled_tasks=()):
        self.enabled_tasks = set(enabled_tasks)
        self.bind_calls = []

    def is_task_enabled(self, task):
        return task in self.enabled_tasks

    def bind(self, task):
        self.bind_calls.append(task)


class OpsiMeowfficerDispatchTest(unittest.TestCase):
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

    def test_skips_disabled_candidates_and_falls_back_to_meowfficer(self):
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
        self.assertEqual(checks, ['OpsiAbyssal', 'OpsiObscure'])
        self.assertEqual(
            config.bind_calls,
            ['OpsiAbyssal', 'OpsiObscure', 'OpsiMeowfficerFarming'],
        )
        self.assertEqual(fallback_calls, [True])


if __name__ == '__main__':
    unittest.main()
