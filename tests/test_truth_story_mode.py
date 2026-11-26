import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.coalition.assets import VERITAS_MODE_BATTLE, VERITAS_MODE_STORY
from module.coalition import ui as coalition_ui
from module.coalition.ui import CoalitionUI
from module.exception import RequestHumanTakeover
from module.eventstory.eventstory_20261124 import EventStory20261124

TRUTH_EVENT = 'coalition_20261124'


class TruthAcademyStoryModeTest(unittest.TestCase):
    def make_ui(self, server='cn'):
        ui = CoalitionUI.__new__(CoalitionUI)
        ui.config = SimpleNamespace(SERVER=server, Campaign_Event=TRUTH_EVENT)
        ui.device = SimpleNamespace(image=object(), click=Mock(), screenshot=Mock(), sleep=Mock())
        ui.ui_page_appear = Mock(return_value=True)
        return ui

    def test_cn_truth_story_and_battle_switch_from_each_known_mode(self):
        for start, target, button in (
                ('battle', 'story', VERITAS_MODE_STORY),
                ('story', 'battle', VERITAS_MODE_BATTLE)):
            ui = self.make_ui()
            with patch.object(coalition_ui.TruthAcademyReader, 'read', return_value='unknown') as reader, \
                    patch.object(coalition_ui.VeritasSwitch, 'get', side_effect=[start, target]):
                ui.coalition_ensure_mode(TRUTH_EVENT, target)
            ui.ui_page_appear.assert_called_once_with(coalition_ui.page_coalition, offset=(20, 20))
            reader.assert_not_called()
            ui.device.click.assert_called_once_with(button)
            ui.device.sleep.assert_called_once_with(0.2)
            ui.device.screenshot.assert_called_once_with()

    def test_unknown_reader_with_native_page_and_story_mode_is_allowed(self):
        ui = self.make_ui()
        with patch.object(coalition_ui.TruthAcademyReader, 'read', return_value='unknown') as reader, \
                patch.object(coalition_ui.VeritasSwitch, 'get', return_value='story'):
            ui.coalition_ensure_mode(TRUTH_EVENT, 'story')
        ui.ui_page_appear.assert_called_once_with(coalition_ui.page_coalition, offset=(20, 20))
        reader.assert_not_called()
        ui.device.click.assert_not_called()

    def test_native_page_false_refuses_without_mode_detection_or_click(self):
        ui = self.make_ui()
        ui.ui_page_appear.return_value = False
        with patch.object(coalition_ui.TruthAcademyReader, 'read', return_value='unknown') as reader, \
                patch.object(coalition_ui.VeritasSwitch, 'get') as get:
            with self.assertRaises(RequestHumanTakeover):
                ui.coalition_ensure_mode(TRUTH_EVENT, 'story')
        ui.ui_page_appear.assert_called_once_with(coalition_ui.page_coalition, offset=(20, 20))
        reader.assert_not_called()
        get.assert_not_called()
        ui.device.click.assert_not_called()

    def test_unknown_initial_mode_or_transition_refuses_without_blind_retry(self):
        ui = self.make_ui()
        with patch.object(coalition_ui.VeritasSwitch, 'get', return_value='unknown'):
            with self.assertRaises(RequestHumanTakeover):
                ui.coalition_ensure_mode(TRUTH_EVENT, 'story')
        ui.device.click.assert_not_called()

        ui = self.make_ui()
        with patch.object(coalition_ui.VeritasSwitch, 'get', side_effect=['battle', 'unknown']):
            with self.assertRaises(RequestHumanTakeover):
                ui.coalition_ensure_mode(TRUTH_EVENT, 'story')
        ui.device.click.assert_called_once_with(VERITAS_MODE_STORY)
        ui.device.screenshot.assert_called_once_with()

    def test_invalid_truth_mode_refuses_without_page_detection_or_click(self):
        ui = self.make_ui()
        with patch.object(coalition_ui.TruthAcademyReader, 'read') as read:
            with self.assertRaises(RequestHumanTakeover):
                ui.coalition_ensure_mode(TRUTH_EVENT, 'story-and-battle')
        read.assert_not_called()
        ui.ui_page_appear.assert_not_called()
        ui.device.click.assert_not_called()

    def make_event_story(self, states):
        event = EventStory20261124.__new__(EventStory20261124)
        event.config = SimpleNamespace(SERVER='cn', Campaign_Event=TRUTH_EVENT)
        event.device = SimpleNamespace(image=object(), click=Mock(), screenshot=Mock(), sleep=Mock())
        event.ui_ensure = Mock()
        event.ui_page_appear = Mock(return_value=True)
        event.loop = lambda: iter([None])
        event.get_event_story_state = Mock(side_effect=states)
        return event

    def test_actual_event_story_entry_uses_native_page_gate_and_story_mode(self):
        event = self.make_event_story(['story'])
        with patch.object(coalition_ui.TruthAcademyReader, 'read', return_value='unknown') as reader, \
                patch.object(coalition_ui.VeritasSwitch, 'get', side_effect=['battle', 'story']):
            state = event.ui_goto_event_story()
        self.assertEqual(state, 'story')
        event.ui_page_appear.assert_called_once_with(coalition_ui.page_coalition, offset=(20, 20))
        reader.assert_not_called()
        event.device.click.assert_called_once_with(VERITAS_MODE_STORY)

    def test_actual_event_story_retry_can_return_to_battle_then_story(self):
        event = self.make_event_story(['unknown', 'story'])
        with patch.object(coalition_ui.TruthAcademyReader, 'read', return_value='unknown') as reader, \
                patch.object(coalition_ui.VeritasSwitch, 'get',
                             side_effect=['story', 'story', 'battle', 'battle', 'story']):
            state = event.ui_goto_event_story()
        self.assertEqual(state, 'story')
        reader.assert_not_called()
        self.assertEqual(event.device.click.call_args_list,
                         [unittest.mock.call(VERITAS_MODE_BATTLE),
                          unittest.mock.call(VERITAS_MODE_STORY)])

    def test_non_cn_path_keeps_existing_switch_set_contract(self):
        ui = self.make_ui(server='en')
        with patch.object(coalition_ui.Switch, 'set', return_value=True) as native_set:
            ui.coalition_ensure_mode(TRUTH_EVENT, 'story')
        native_set.assert_called_once()
        self.assertEqual(native_set.call_args[0][0], 'story')
        ui.ui_page_appear.assert_not_called()
        ui.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
