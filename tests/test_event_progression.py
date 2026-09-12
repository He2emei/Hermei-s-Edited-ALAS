import json
import unittest
from unittest.mock import patch

from module.config.config_generated import GeneratedConfig
from module.handler.fast_forward import FastForwardHandler


class EventProgressionConfig:
    Scheduler_Command = 'Event'
    EventFleet_AutoPrepare = True
    StopCondition_StageIncrease = True
    Campaign_Event = 'event_test'
    Campaign_Name = 'A1'
    Scheduler_Enable = True
    STAGE_INCREASE_AB = False
    STAGE_INCREASE_CUSTOM = ''

    def __init__(self):
        self.cross_sets = []
        self.task_calls = []

    def cross_set(self, keys, value):
        self.cross_sets.append((keys, value))

    def task_call(self, task):
        self.task_calls.append(task)


def handler_at(stage, *, auto_prepare=True, command='Event'):
    config = EventProgressionConfig()
    config.Campaign_Name = stage
    config.EventFleet_AutoPrepare = auto_prepare
    config.Scheduler_Command = command
    handler = object.__new__(FastForwardHandler)
    handler.config = config
    return handler, config


class EventProgressionTest(unittest.TestCase):
    @patch('module.handler.fast_forward.map_files', return_value=['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1'])
    def test_b3_increases_to_c1(self, _map_files):
        handler, config = handler_at('B3')

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'C1')
        self.assertTrue(config.Scheduler_Enable)
        self.assertEqual(config.task_calls, [])

    @patch('module.handler.fast_forward.map_files', return_value=['c1', 'c2', 'c3', 'd1'])
    def test_c3_increases_to_d1(self, _map_files):
        handler, config = handler_at('C3')

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'D1')

    @patch('module.handler.fast_forward.map_files', return_value=['a1', 'b1', 'c1', 'd3', 'sp'])
    def test_d3_hands_off_to_sp_without_ex(self, _map_files):
        handler, config = handler_at('D3')

        handler.handle_map_stop()

        self.assertFalse(config.Scheduler_Enable)
        self.assertEqual(config.task_calls, ['EventSp'])
        self.assertIn(('EventSp.Campaign.Event', 'event_test'), config.cross_sets)
        self.assertIn(('EventSp.Campaign.Name', 'sp'), config.cross_sets)
        self.assertIn(('EventSp.EventFleet.AutoPrepare', True), config.cross_sets)

    @patch('module.handler.fast_forward.map_files', return_value=['a1', 'b3', 'c2'])
    def test_missing_c1_stops_without_advancing(self, _map_files):
        handler, config = handler_at('B3')

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'B3')
        self.assertFalse(config.Scheduler_Enable)
        self.assertEqual(config.task_calls, [])

    @patch('module.handler.fast_forward.map_files', return_value=['d3'])
    def test_missing_sp_stops_at_d3(self, _map_files):
        handler, config = handler_at('D3')

        handler.handle_map_stop()

        self.assertFalse(config.Scheduler_Enable)
        self.assertEqual(config.task_calls, [])

    @patch('module.handler.fast_forward.map_files', return_value=['b3', 'c1'])
    def test_disabled_auto_prepare_preserves_legacy_stage_progression(self, _map_files):
        handler, config = handler_at('B3', auto_prepare=False)

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'B3')
        self.assertFalse(config.Scheduler_Enable)

    @patch('module.handler.fast_forward.map_files', return_value=['b3', 'c1'])
    def test_non_event_command_preserves_legacy_stage_progression(self, _map_files):
        handler, config = handler_at('B3', command='Event2')

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'B3')
        self.assertFalse(config.Scheduler_Enable)

    @patch('module.handler.fast_forward.map_files', return_value=['t1', 't2'])
    def test_non_abcd_stage_uses_legacy_progression(self, _map_files):
        handler, config = handler_at('T1')

        handler.handle_map_stop()

        self.assertEqual(config.Campaign_Name, 'T2')
        self.assertTrue(config.Scheduler_Enable)

    def test_event_fleet_schema_is_registered_for_event_tasks(self):
        with open('module/config/argument/args.json', encoding='utf-8') as file:
            args = json.load(file)

        for task in ('Event', 'Event2', 'EventC', 'EventD', 'EventSp'):
            with self.subTest(task=task):
                self.assertEqual(args[task]['EventFleet']['AutoPrepare']['value'], False)
        self.assertFalse(GeneratedConfig.EventFleet_AutoPrepare)


if __name__ == '__main__':
    unittest.main()
