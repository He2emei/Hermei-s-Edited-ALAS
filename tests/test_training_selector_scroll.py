import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import cv2

from module.exception import RequestHumanTakeover
from module.os.training import TrainingFleetManager


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'opsi_training'


def image(name):
    value = cv2.imread(str(FIXTURES / name))
    if value is None:
        raise AssertionError(f'Missing fixture: {name}')
    return cv2.cvtColor(value, cv2.COLOR_BGR2RGB)


class TrainingSelectorScrollTest(unittest.TestCase):
    def make_manager(self, frames):
        manager = TrainingFleetManager.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(
            image=frames[0],
            screenshot=Mock(),
            sleep=Mock(),
            swipe_vector=Mock(),
            click=Mock(),
        )
        manager._wait = Mock()
        manager._label = Mock(return_value='舰队部署')

        def screenshot():
            if len(frames) > 1:
                frames.pop(0)
            manager.device.image = frames[0]

        manager.device.screenshot.side_effect = screenshot

        manager._close_selector = Mock(wraps=manager._close_selector)
        return manager

    def test_open_selector_retries_hidden_row_until_real_matcher_finds_it(self):
        manager = self.make_manager([
            image('config1-selector-row-hidden.png'),
            image('config1-selector-row-hidden.png'),
            image('config1-selector-row-visible.png'),
        ])
        opsi = SimpleNamespace(ensure_no_map_event=Mock(), order_enter=Mock(), is_in_map=Mock())

        manager._open_selector(opsi)

        self.assertEqual(manager._fourth_row_y(), 336)
        self.assertEqual(manager.device.swipe_vector.call_count, 2)
        self.assertEqual(manager.device.swipe_vector.call_args_list[0][1]['duration'], (0.4, 0.6))
        self.assertEqual(manager.device.swipe_vector.call_args_list[1][1]['duration'], (0.4, 0.6))
        manager.device.sleep.assert_has_calls([call(0.6), call(0.6)])
        manager._wait.assert_called_once()
        manager.device.click.assert_called_once()
        manager._close_selector.assert_not_called()

    def test_open_selector_does_not_swipe_when_row_is_already_visible(self):
        manager = self.make_manager([image('config1-selector-row-visible.png')])
        opsi = SimpleNamespace(ensure_no_map_event=Mock(), order_enter=Mock(), is_in_map=Mock())

        manager._open_selector(opsi)

        self.assertEqual(manager._fourth_row_y(), 336)
        manager.device.swipe_vector.assert_not_called()
        manager._close_selector.assert_not_called()

    def test_open_selector_stops_after_bounded_no_progress_and_closes_known_selector(self):
        hidden = image('config1-selector-row-hidden.png')
        manager = self.make_manager([hidden, hidden.copy(), hidden.copy(), hidden.copy()])
        opsi = SimpleNamespace(ensure_no_map_event=Mock(), order_enter=Mock(), is_in_map=Mock())

        with self.assertRaisesRegex(RequestHumanTakeover, 'Cannot locate fourth fleet row'):
            manager._open_selector(opsi)

        self.assertLessEqual(manager.device.swipe_vector.call_count, 3)
        manager._close_selector.assert_called_once_with(opsi)
        self.assertEqual(manager.device.click.call_count, 2)  # enter and safe close

    def test_open_selector_does_not_swipe_or_close_when_ui_becomes_unknown(self):
        unknown = image('config1-selector-row-hidden.png').copy()
        unknown[:125, 110:330] = 0
        manager = self.make_manager([image('config1-selector-row-hidden.png'), unknown])
        opsi = SimpleNamespace(ensure_no_map_event=Mock(), order_enter=Mock(), is_in_map=Mock())

        with self.assertRaisesRegex(RequestHumanTakeover, 'selector'):
            manager._open_selector(opsi)

        self.assertEqual(manager.device.swipe_vector.call_count, 1)
        manager._close_selector.assert_not_called()
        self.assertEqual(manager.device.click.call_count, 1)  # deployment entry only


if __name__ == '__main__':
    unittest.main()
