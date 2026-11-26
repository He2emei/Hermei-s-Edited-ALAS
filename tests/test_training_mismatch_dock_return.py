from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.exception import RequestHumanTakeover
from module.retire.assets import DOCK_CHECK
from module.ui.assets import BACK_ARROW
from module.os.training_ui import TrainingShipInspector


class BottomScroll:
    edge_threshold = 0.05

    def set_top(self, main):
        pass

    def cal_position(self, main):
        return 1.0


class TrainingMismatchDockReturnTest(unittest.TestCase):
    def make_inspector(self, dock_matches):
        inspector = TrainingShipInspector.__new__(TrainingShipInspector)
        inspector.ui_ensure = Mock()
        inspector.dock_favourite_set = Mock()
        inspector.dock_sort_method_dsc_set = Mock()
        inspector.dock_filter_set = Mock()
        inspector.ship_info_enter = Mock()
        inspector.read_ship = Mock(return_value=SimpleNamespace(name='独角兽', level=100))
        inspector.device = SimpleNamespace(image=object(), screenshot=Mock(), click=Mock())
        inspector.wait_until_appear = Mock(return_value=None)

        def appear(button, **kwargs):
            return bool(dock_matches) if button is DOCK_CHECK else False
        inspector.appear = Mock(side_effect=appear)
        return inspector

    def run_scan(self, inspector, decide):
        card = SimpleNamespace(area=(10, 20, 150, 70))
        levels = SimpleNamespace(ocr=Mock(return_value=[100]))
        names = SimpleNamespace(ocr=Mock(return_value=['企业']))
        with patch('module.os.training_ui.dock_cards', return_value=[card]), \
                patch('module.os.training_ui.dock_card_lock', return_value=True), \
                patch('module.os.training_ui.LevelOcr', return_value=levels), \
                patch('module.os.training_ui.Ocr', return_value=names):
            return inspector.find_candidates(
                side='main', factions=set(), excluded=set(), needed=1,
                scroll=BottomScroll(), decide_candidate=decide)

    def test_native_void_wait_then_confirmed_dock_is_not_misread_as_failure(self):
        """This fails on the old `if not wait_until_appear(...)` branch."""
        inspector = self.make_inspector(dock_matches=True)
        decide = Mock()
        found = self.run_scan(inspector, decide)

        self.assertEqual(found, [])
        inspector.wait_until_appear.assert_called_once_with(DOCK_CHECK, offset=(20, 20))
        inspector.appear.assert_any_call(DOCK_CHECK, offset=(20, 20))
        inspector.device.click.assert_called_once_with(BACK_ARROW)
        inspector.ship_info_enter.assert_called_once()
        # Mismatched identity is quarantined; it is never evaluated for training.
        decide.assert_not_called()

    def test_void_wait_without_confirmed_dock_still_takes_over(self):
        inspector = self.make_inspector(dock_matches=False)
        with self.assertRaises(RequestHumanTakeover):
            self.run_scan(inspector, Mock())
        inspector.wait_until_appear.assert_called_once_with(DOCK_CHECK, offset=(20, 20))
        inspector.appear.assert_any_call(DOCK_CHECK, offset=(20, 20))
        inspector.device.click.assert_called_once_with(BACK_ARROW)


if __name__ == '__main__':
    unittest.main()
