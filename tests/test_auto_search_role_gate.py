import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import RequestHumanTakeover
from module.handler.fast_forward import FastForwardHandler
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.map.map_operation import MapOperation


class AutoSearchRoleGateTest(unittest.TestCase):
    def make_main(self, *, enabled=True, submarine=False):
        return SimpleNamespace(
            map_is_auto_search=enabled,
            config=SimpleNamespace(
                Fleet_FleetOrder='fleet1_all_fleet2_standby',
                SUBMARINE=submarine,
                Submarine_AutoSearchMode='sub_standby',
            ),
            fleet_preparation_sidebar_ensure=Mock(return_value=True),
            auto_search_setting_ensure=Mock(return_value=True),
        )

    def test_auto_search_disabled_returns_false_without_touching_roles(self):
        main = self.make_main(enabled=False, submarine=True)

        self.assertFalse(FastForwardHandler.handle_auto_search_setting(main))

        main.fleet_preparation_sidebar_ensure.assert_not_called()
        main.auto_search_setting_ensure.assert_not_called()

    def test_success_without_submarine_ensures_only_fleet_role(self):
        main = self.make_main(submarine=False)

        self.assertTrue(FastForwardHandler.handle_auto_search_setting(main))

        main.fleet_preparation_sidebar_ensure.assert_called_once_with(3)
        main.auto_search_setting_ensure.assert_called_once_with('fleet1_all_fleet2_standby')

    def test_success_ensures_sidebar_fleet_and_submarine_in_order(self):
        main = self.make_main(submarine=True)

        self.assertTrue(FastForwardHandler.handle_auto_search_setting(main))

        main.fleet_preparation_sidebar_ensure.assert_called_once_with(3)
        main.auto_search_setting_ensure.assert_has_calls([
            call('fleet1_all_fleet2_standby'),
            call('sub_standby'),
        ])

    def test_sidebar_failure_stops_before_fleet_and_submarine_roles(self):
        main = self.make_main(submarine=True)
        main.fleet_preparation_sidebar_ensure.return_value = False

        with self.assertRaisesRegex(RequestHumanTakeover, 'sidebar could not be selected'):
            FastForwardHandler.handle_auto_search_setting(main)

        main.auto_search_setting_ensure.assert_not_called()

    def test_fleet_role_failure_stops_before_submarine_role(self):
        main = self.make_main(submarine=True)
        main.auto_search_setting_ensure.return_value = False

        with self.assertRaisesRegex(RequestHumanTakeover, 'fleet role could not be ensured'):
            FastForwardHandler.handle_auto_search_setting(main)

        main.auto_search_setting_ensure.assert_called_once_with('fleet1_all_fleet2_standby')

    def test_submarine_role_failure_requests_takeover(self):
        main = self.make_main(submarine=True)
        main.auto_search_setting_ensure.side_effect = [True, False]

        with self.assertRaisesRegex(RequestHumanTakeover, 'submarine role could not be ensured'):
            FastForwardHandler.handle_auto_search_setting(main)

        main.auto_search_setting_ensure.assert_has_calls([
            call('fleet1_all_fleet2_standby'),
            call('sub_standby'),
        ])

    def make_enter_map_main(self, *, sidebar_ok=False, fleet_role_ok=True):
        main = MapOperation.__new__(MapOperation)
        main.config = SimpleNamespace(
            campaign_name='GemsFarming',
            DropRecord_CombatRecord=False,
            StopCondition_MapAchievement='non_stop',
            Fleet_FleetOrder='fleet1_all_fleet2_standby',
            SUBMARINE=False,
        )
        clicks = []

        class UnsafePaidEntry(Exception):
            pass

        def click(button):
            clicks.append(button)
            if button is FLEET_PREPARATION:
                raise UnsafePaidEntry('paid entry sentinel reached')

        main.device = SimpleNamespace(click=Mock(side_effect=click), screenshot=Mock())
        main.clicks = clicks
        main.UnsafePaidEntry = UnsafePaidEntry
        main.stat = SimpleNamespace(new=Mock(return_value=nullcontext()))
        main.map_clear_percentage_timer = SimpleNamespace(reset=Mock())
        main.map_fleet_checked = False
        main.is_in_map = Mock(return_value=False)
        main.appear = Mock(side_effect=lambda button, **kwargs: button is FLEET_PREPARATION)
        main.handle_map_mode_switch = Mock(return_value=True)
        main.handle_map_preparation = Mock(side_effect=[MAP_PREPARATION, None])
        main.map_get_info = Mock()
        main.handle_map_walk_speedup = Mock()
        main.handle_fast_forward = Mock()
        main.handle_auto_search = Mock()
        main.triggered_map_stop = Mock(return_value=False)
        main.handle_2x_book_setting = Mock()
        main.fleet_preparation = Mock()
        main.handle_auto_submarine_call_disable = Mock()
        main.fleet_preparation_sidebar_ensure = Mock(return_value=sidebar_ok)
        main.auto_search_setting_ensure = Mock(return_value=fleet_role_ok)
        main.map_is_auto_search = True
        return main

    def run_enter_map(self, main):
        class ImmediateTimer:
            def __init__(self, *args, **kwargs):
                pass

            def reached(self):
                return True

            def reset(self):
                pass

        with patch('module.map.map_operation.Timer', ImmediateTimer):
            MapOperation.enter_map(main, button=object(), mode='normal', skip_first_screenshot=False)

    def test_enter_map_stops_before_paid_entry_when_role_gate_fails(self):
        main = self.make_enter_map_main()

        with self.assertRaisesRegex(RequestHumanTakeover, 'sidebar could not be selected'):
            self.run_enter_map(main)

        self.assertEqual(main.clicks, [MAP_PREPARATION])

    def test_enter_map_stops_before_paid_entry_when_fleet_role_fails(self):
        main = self.make_enter_map_main(sidebar_ok=True, fleet_role_ok=False)

        with self.assertRaisesRegex(RequestHumanTakeover, 'fleet role could not be ensured'):
            self.run_enter_map(main)

        main.fleet_preparation_sidebar_ensure.assert_called_once_with(3)
        main.auto_search_setting_ensure.assert_called_once_with('fleet1_all_fleet2_standby')
        self.assertEqual(main.clicks, [MAP_PREPARATION])



if __name__ == '__main__':
    unittest.main()
