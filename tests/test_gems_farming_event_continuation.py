import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.gems_farming import GemsFarming
from module.campaign.run import CampaignRun


class StopTask(Exception):
    pass


class FakeConfig(SimpleNamespace):
    def override(self, **values):
        if not hasattr(self, 'overridden'):
            self.overridden = {}
        for key, value in values.items():
            self.overridden[key] = value
            setattr(self, key, value)

    def reload(self):
        for key, value in getattr(self, 'overridden', {}).items():
            setattr(self, key, value)

    def task_switched(self):
        return False

    def task_delay(self, **kwargs):
        self.delay_calls.append(kwargs)

    def task_stop(self):
        self.stop_calls += 1
        raise StopTask


class GemsFarmingEventContinuationTest(unittest.TestCase):
    def _runner(self, *, profile='event', mode='normal', flagship='ship', vanguard='disabled'):
        base = FakeConfig(
            campaign_profile=SimpleNamespace(mode=profile),
            Campaign_Mode=mode,
            GemsFarming_ChangeFlagship=flagship,
            GemsFarming_ChangeVanguard=vanguard,
            StopCondition_RunCount=0,
            Scheduler_Enable=True,
            delay_calls=[],
            stop_calls=0,
        )
        record = FakeConfig(
            STOP_IF_REACH_LV32=True,
            LV32_TRIGGERED=False,
            GEMS_EMOTION_TRIGGERED=False,
            Emotion_Fleet1Value=84,
        )
        record.set_record = Mock(side_effect=lambda **values: [setattr(record, key, value) for key, value in values.items()])
        runner = object.__new__(GemsFarming)
        runner.config = base
        runner.campaign = SimpleNamespace(config=record, _map_battle=1, emotion=SimpleNamespace(reduce_per_battle=1),
                                         ensure_auto_search_exit=Mock())
        runner._trigger_lv32 = False
        runner._trigger_emotion = False
        runner._new_fleet_emotion = 150
        runner._no_flagship_candidate = False
        return runner

    @staticmethod
    def _install_two_run_cycle(runner, *, emotion=False, on_second=None):
        calls = []

        def one_campaign_run(self, name, folder='campaign_main', mode='normal', total=0):
            if len(calls) > 0:
                self.config.reload()
                self.campaign.config.reload()
            calls.append((name, folder, mode, self.config.STOP_IF_REACH_LV32,
                          self.campaign.config.STOP_IF_REACH_LV32))
            if len(calls) == 1:
                self.campaign.config.LV32_TRIGGERED = True
                self.triggered_stop_condition()
                self.campaign.config.GEMS_EMOTION_TRIGGERED = emotion
            elif on_second:
                on_second(self)
            else:
                self.campaign.config.LV32_TRIGGERED = False
                self.campaign.config.GEMS_EMOTION_TRIGGERED = False
                self.triggered_stop_condition(oil_check=True)

        patcher = patch.object(CampaignRun, 'run', new=one_campaign_run)
        patcher.start()
        return calls, patcher

    @staticmethod
    def _known_no_candidate(runner):
        runner._no_flagship_candidate = True
        runner._new_fleet_emotion = 0
        return False

    def test_event_normal_a3_known_no_cv_runs_next_cycle_and_preserves_emotion(self):
        runner = self._runner()
        calls, patcher = self._install_two_run_cycle(runner)
        runner.flagship_change = Mock(side_effect=lambda: self._known_no_candidate(runner))
        parent_stop = patch.object(CampaignRun, 'triggered_stop_condition', return_value=False)
        parent_stop_mock = parent_stop.start()
        try:
            runner.run(name='A3', folder='event_20250520_cn', mode='normal')
        finally:
            patcher.stop()
            parent_stop.stop()

        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[1][3])
        self.assertFalse(calls[1][4])
        self.assertEqual(runner.config.delay_calls, [])
        self.assertEqual(runner.config.stop_calls, 0)
        self.assertEqual(runner.campaign.config.Emotion_Fleet1Value, 84)
        runner.campaign.config.set_record.assert_not_called()
        self.assertTrue(runner.config.STOP_IF_REACH_LV32)
        self.assertTrue(runner.campaign.config.STOP_IF_REACH_LV32)
        self.assertTrue(runner.config.overridden['STOP_IF_REACH_LV32'])
        self.assertTrue(runner.campaign.config.overridden['STOP_IF_REACH_LV32'])
        parent_stop_mock.assert_called_once_with(oil_check=True)

    def test_normal_candidate_replacement_keeps_existing_continuation(self):
        runner = self._runner()
        calls, patcher = self._install_two_run_cycle(runner)
        parent_stop = patch.object(CampaignRun, 'triggered_stop_condition', return_value=False)
        parent_stop_mock = parent_stop.start()
        def replace_flagship():
            runner._new_fleet_emotion = 121
            return True

        runner.flagship_change = Mock(side_effect=replace_flagship)
        try:
            runner.run(name='A3', folder='event_20250520_cn', mode='normal')
        finally:
            patcher.stop()
            parent_stop.stop()

        self.assertEqual(len(calls), 2)
        runner.campaign.config.set_record.assert_called_once_with(Emotion_Fleet1Value=121)
        self.assertEqual(runner.config.delay_calls, [])
        parent_stop_mock.assert_called_once_with(oil_check=True)

    def test_fallback_is_denied_for_out_of_scope_conditions(self):
        variants = (
            {'profile': 'daily'},
            {'mode': 'hard'},
            {'name': 'A2'},
            {'folder': 'campaign_main'},
            {'folder': 'event-test'},
            {'flagship': 'ship_equip'},
            {'vanguard': 'ship'},
            {'emotion': True},
            {'known_marker': False},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                runner = self._runner(**{key: value for key, value in variant.items()
                                         if key in {'profile', 'mode', 'flagship', 'vanguard'}})
                calls, patcher = self._install_two_run_cycle(runner, emotion=variant.get('emotion', False))

                def failed_change():
                    if variant.get('known_marker', True):
                        runner._no_flagship_candidate = True
                    runner._new_fleet_emotion = 0
                    return False

                runner.flagship_change = Mock(side_effect=failed_change)
                try:
                    with self.assertRaises(StopTask):
                        runner.run(name=variant.get('name', 'A3'),
                                   folder=variant.get('folder', 'event_20250520_cn'), mode=variant.get('mode', 'normal'))
                finally:
                    patcher.stop()

                self.assertEqual(len(calls), 1)
                self.assertEqual(runner.config.delay_calls, [{'minute': 30}])
                self.assertEqual(runner.config.stop_calls, 1)
                runner.campaign.config.set_record.assert_called_once_with(Emotion_Fleet1Value=0)

    def test_exception_during_flagship_change_propagates(self):
        runner = self._runner()
        calls, patcher = self._install_two_run_cycle(runner)
        runner.flagship_change = Mock(side_effect=RuntimeError('unknown failure'))
        try:
            with self.assertRaisesRegex(RuntimeError, 'unknown failure'):
                runner.run(name='A3', folder='event_20250520_cn', mode='normal')
        finally:
            patcher.stop()
        self.assertEqual(len(calls), 1)
        self.assertEqual(runner.config.delay_calls, [])
        runner.campaign.config.set_record.assert_not_called()

    def test_normal_no_candidate_branch_sets_narrow_marker(self):
        runner = self._runner()
        runner.ui_enter_ship = Mock()
        runner.get_common_rarity_cv = Mock(return_value=[])
        runner.dock_reset = Mock()
        runner.ui_leave_ship = Mock()
        runner._new_fleet_emotion = 150
        runner._no_flagship_candidate = False

        self.assertFalse(runner.flagship_change_execute())
        self.assertTrue(runner._no_flagship_candidate)
        self.assertEqual(runner._new_fleet_emotion, 0)

    def test_normal_candidate_change_clears_no_candidate_marker(self):
        runner = self._runner()
        ship = SimpleNamespace(level=12, emotion=120, button='ship-card')
        runner.ui_enter_ship = Mock()
        runner.get_common_rarity_cv = Mock(return_value=[ship])
        runner.dock_select_one = Mock()
        runner.dock_reset = Mock()
        runner.dock_select_confirm = Mock()
        runner._new_fleet_emotion = 150
        runner._no_flagship_candidate = True

        self.assertTrue(runner.flagship_change_execute())
        self.assertFalse(runner._no_flagship_candidate)
        self.assertEqual(runner._new_fleet_emotion, 120)


if __name__ == '__main__':
    unittest.main()



