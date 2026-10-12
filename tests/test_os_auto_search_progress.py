import unittest
from unittest.mock import Mock, patch

from module.exception import RequestHumanTakeover
from module.os.map import OSMap


class FakeClock:
    def __init__(self, value=0):
        self.value = value

    def monotonic(self):
        value = self.value
        self.value += 100
        return value


class FakeTimer:
    def __init__(self, *args, **kwargs):
        self.seconds = args[0] if args else None
        self.count = kwargs.get('count')
        self.ready = self.seconds == 5 and self.count is None

    def start(self):
        return self

    def reached(self):
        return self.ready

    def reset(self):
        self.ready = False


class OpsiAutoSearchProgressTest(unittest.TestCase):
    def make_map(self, command='OpsiHazard1Leveling', switched=False, in_map=True):
        app = OSMap.__new__(OSMap)
        app.config = Mock()
        app.config.task.command = command
        app.config.task_switched.return_value = switched
        app.device = Mock()
        app.loop = lambda: range(10)
        app.is_in_map = lambda: in_map
        app.hp_reset = lambda: None
        app.hp_get = lambda: None
        app.appear = lambda *args, **kwargs: False
        app.handle_os_auto_search_map_option = lambda **kwargs: False
        app.handle_retirement = lambda: False
        app.combat_appear = lambda: False
        app.handle_map_event = lambda: False
        app.on_auto_search_battle_count_reset = lambda: None
        app.on_auto_search_battle_count_add = lambda: None
        app.interrupt_auto_search = Mock()
        app.need_repair = []
        return app

    def run_with_clock(self, app, clock):
        return patch('module.os.map.time.monotonic', clock.monotonic), patch(
            'module.os.map.Timer', FakeTimer
        )

    def test_strategic_map_checks_task_switch_and_interrupts(self):
        app = self.make_map(switched=True)
        app.interrupt_auto_search.side_effect = RuntimeError('interrupted')
        clock_patch, timer_patch = self.run_with_clock(app, FakeClock())
        with clock_patch, timer_patch, self.assertRaisesRegex(RuntimeError, 'interrupted'):
            app.os_auto_search_daemon(strategic=True)
        app.interrupt_auto_search.assert_called_once_with()

    def test_non_strategic_map_does_not_interrupt_on_task_switch(self):
        app = self.make_map(switched=True)
        app.device.stuck_record_clear = Mock()
        clock = FakeClock()
        clock_patch, timer_patch = self.run_with_clock(app, clock)
        with clock_patch, timer_patch, self.assertRaises(RequestHumanTakeover) as caught:
            app.os_auto_search_daemon(strategic=False)
        self.assertIn('OpsiHazard1Leveling', str(caught.exception))
        app.interrupt_auto_search.assert_not_called()
        # At the exact 300-second boundary, repeated map frames and stuck
        # record cleanup have not refreshed the business-progress deadline.
        self.assertEqual(app.device.stuck_record_clear.call_count, 3)

    def test_cross_month_timeout_preserves_old_month_protection(self):
        app = self.make_map(command='OpsiCrossMonth', switched=True)
        next_run = object()
        app.config.task.next_run = next_run
        clock_patch, timer_patch = self.run_with_clock(app, FakeClock())
        with clock_patch, timer_patch, self.assertRaises(RequestHumanTakeover) as caught:
            app.os_auto_search_daemon(strategic=True)
        self.assertIn('Overdue OpsiCrossMonth cannot confirm', str(caught.exception))
        app.interrupt_auto_search.assert_not_called()
        app.config.task_switched.assert_not_called()
        self.assertIs(app.config.task.next_run, next_run)

    def test_combat_page_keeps_existing_strategic_task_switch_interrupt(self):
        app = self.make_map(switched=True, in_map=False)
        app.combat_appear = lambda: True
        app.interrupt_auto_search.side_effect = RuntimeError('combat interrupt')
        clock_patch, timer_patch = self.run_with_clock(app, FakeClock())
        with clock_patch, timer_patch, self.assertRaisesRegex(RuntimeError, 'combat interrupt'):
            app.os_auto_search_daemon(strategic=True)
        app.interrupt_auto_search.assert_called_once_with()

    def test_successful_event_resets_deadline(self):
        app = self.make_map()
        app.loop = lambda: range(5)
        event_results = iter([True, False, False, False, False])
        app.handle_map_event = Mock(side_effect=lambda: next(event_results))
        clock = FakeClock()
        # First check after event is at 300 seconds; later checks reach the
        # deadline only after the event's successful handling has reset it.
        clock_patch, timer_patch = self.run_with_clock(app, clock)
        with clock_patch, timer_patch, self.assertRaises(RequestHumanTakeover):
            app.os_auto_search_daemon()
        self.assertEqual(app.handle_map_event.call_count, 4)

    def test_battle_duration_is_excluded_and_return_resets_deadline(self):
        app = self.make_map()
        app.loop = lambda: range(6)
        app.device.stuck_record_clear = Mock()
        battle_results = iter([True, False, False, False, False, False])
        app.combat_appear = lambda: next(battle_results)
        clock = FakeClock()

        def finish_long_battle(**kwargs):
            clock.value += 1000
            return 1

        app.auto_search_combat = finish_long_battle
        clock_patch, timer_patch = self.run_with_clock(app, clock)
        with clock_patch, timer_patch, self.assertRaises(RequestHumanTakeover):
            app.os_auto_search_daemon()
        # The timeout occurs after three complete idle iterations after the
        # nested battle returns, proving that its duration was excluded.
        self.assertEqual(app.device.stuck_record_clear.call_count, 3)

    def test_each_daemon_invocation_starts_a_fresh_deadline(self):
        app = self.make_map()
        app.device.stuck_record_clear = Mock()
        clock = FakeClock()
        clock_patch, timer_patch = self.run_with_clock(app, clock)
        with clock_patch, timer_patch:
            with self.assertRaises(RequestHumanTakeover):
                app.os_auto_search_daemon()
            first_count = app.device.stuck_record_clear.call_count
            with self.assertRaises(RequestHumanTakeover):
                app.os_auto_search_daemon()
        self.assertEqual(first_count, 3)
        self.assertEqual(app.device.stuck_record_clear.call_count, 6)


if __name__ == '__main__':
    unittest.main()
