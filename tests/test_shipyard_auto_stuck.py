import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from module.shipyard.assets import SHIPYARD_MINUS_DEV, SHIPYARD_MINUS_FATE
from module.shipyard.assets import SHIPYARD_SERIES_SELECT_CHECK, SHIPYARD_SERIES_SELECT_ENTER
from module.shipyard.ui import ShipyardUI
from module.shipyard.auto import AutoShipyard
from module.exception import RequestHumanTakeover
from module.ui.page import page_shipyard


class ShipyardUnstartedProjectTest(unittest.TestCase):
    """A panel that cannot be adjusted must be skipped, never waited on.

    Live frames 2026-09-19 (埃吉尔, 科研四期): the project had not been researched
    far enough, so the panel offered 开始研究 and had no quantity row at all —
    verified by re-checking the archived frames: none of the shipyard templates
    matched, including SHIPYARD_MINUS_DEV and SHIPYARD_MINUS_FATE.  AutoShipyard
    nevertheless entered _use_owned, waited for those controls, and raised
    GameStuckError every few minutes until the guard stopped restarting the
    scheduler.
    """

    def test_quantity_controls_decide_adjustability(self):
        class Fake(AutoShipyard):
            def __init__(self, visible):
                self.visible = visible

            def appear(self, button, offset=0):
                return button in self.visible

        self.assertFalse(Fake(set())._quantity_controls_visible())
        self.assertTrue(Fake({SHIPYARD_MINUS_DEV})._quantity_controls_visible())
        self.assertTrue(Fake({SHIPYARD_MINUS_FATE})._quantity_controls_visible())

    def test_candidate_without_controls_is_unbuilt(self):
        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def _quantity_controls_visible(self):
                return False

            def _use_owned(self, index):
                raise AssertionError('quantity handling must not be reached')

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        with mock.patch('module.shipyard.auto.required_level', return_value=None):
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', False), 'unbuilt')

    def test_candidate_still_uses_owned_blueprints_when_controls_exist(self):
        calls = []

        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def _quantity_controls_visible(self):
                return True

            def _use_owned(self, index):
                calls.append(index)
                return False

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        with mock.patch('module.shipyard.auto.required_level', return_value=None):
            with mock.patch.object(Fake, 'auto_full', return_value=False):
                self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', False), 'retry')
        # The owned-blueprint path is reached exactly once, then the candidate
        # reports retry; it must not fall through to the quantity controls again.
        self.assertEqual(calls, [1])

    def test_unreadable_level_target_defers_and_closes_book_dialog_on_leveler(self):
        """One bad level target must not end the whole daily catch-up.

        Live 2026-09-19 04:38: the Shipyard pass died with "Request human
        takeover" while scanning the dock for a level target, which stopped the
        scheduler and, with it, every later task in the queue.
        """

        fake = self._make_leveling_fake()
        with mock.patch('module.shipyard.auto.required_level', return_value=10), \
                mock.patch('module.shipyard.auto.ShipyardLeveler') as leveler:
            leveler_instance = leveler.return_value
            leveler_instance.meet_level.side_effect = RequestHumanTakeover(
                'dock filter does not surface the level target')
            leveler_instance._book_dialog.return_value = True
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', True), 'level')
            leveler_instance._book_dialog.assert_called_once_with()
            leveler_instance._book_click.assert_called_once_with(986, 132, 'SHIPYARD_BOOK_CLOSE')
            fake.ui_ensure.assert_called_once_with(page_shipyard)

    def test_unreadable_level_target_without_book_dialog_only_returns_to_shipyard(self):
        fake = self._make_leveling_fake()
        with mock.patch('module.shipyard.auto.required_level', return_value=10), \
                mock.patch('module.shipyard.auto.ShipyardLeveler') as leveler:
            leveler_instance = leveler.return_value
            leveler_instance.meet_level.side_effect = RequestHumanTakeover('target unavailable')
            leveler_instance._book_dialog.return_value = False
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', True), 'level')
            leveler_instance._book_dialog.assert_called_once_with()
            leveler_instance._book_click.assert_not_called()
            fake.ui_ensure.assert_called_once_with(page_shipyard)

    def test_unreadable_level_target_ignores_close_request_and_still_returns_to_shipyard(self):
        fake = self._make_leveling_fake()
        with mock.patch('module.shipyard.auto.required_level', return_value=10), \
                mock.patch('module.shipyard.auto.ShipyardLeveler') as leveler:
            leveler_instance = leveler.return_value
            leveler_instance.meet_level.side_effect = RequestHumanTakeover('target unavailable')
            leveler_instance._book_dialog.return_value = True
            leveler_instance._book_click.side_effect = RequestHumanTakeover('close failed')
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', True), 'level')
            leveler_instance._book_click.assert_called_once_with(986, 132, 'SHIPYARD_BOOK_CLOSE')
            fake.ui_ensure.assert_called_once_with(page_shipyard)

    @staticmethod
    def _make_leveling_fake():
        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def ui_ensure(self, page):
                return None

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        fake.config = SimpleNamespace(ShipyardAuto_UseExpBooks=True)
        fake.ui_ensure = mock.Mock()
        return fake


class ShipyardSeriesDetectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).parent / 'fixtures' / 'shipyard_series_current_20261004.png'
        cls.image = np.asarray(Image.open(fixture).convert('RGB'))
        selector_fixture = Path(__file__).parent / 'fixtures' / 'shipyard_series_selector_20261004.png'
        cls.selector_image = np.asarray(Image.open(selector_fixture).convert('RGB'))

    def make_ui(self, image=None):
        ui = ShipyardUI.__new__(ShipyardUI)
        ui.device = SimpleNamespace(image=self.image if image is None else image,
                                    stuck_record_add=lambda button: None)
        return ui

    def test_built_shipyard_with_series_entry_and_dev_control_is_recognized(self):
        ui = self.make_ui()
        self.assertTrue(ui.appear(SHIPYARD_SERIES_SELECT_ENTER, offset=(20, 20)))
        self.assertTrue(ui.appear(SHIPYARD_MINUS_DEV, offset=(20, 20)))
        self.assertTrue(ui._shipyard_in_ui())

    def test_empty_frame_is_not_shipyard(self):
        self.assertFalse(self.make_ui(np.zeros_like(self.image))._shipyard_in_ui())

    def test_series_entry_alone_is_not_shipyard(self):
        image = self.image.copy()
        image[429:463, 1049:1084] = 0
        image[453:487, 1028:1063] = 0
        ui = self.make_ui(image)
        self.assertTrue(ui.appear(SHIPYARD_SERIES_SELECT_ENTER, offset=(20, 20)))
        self.assertFalse(ui.appear(SHIPYARD_MINUS_FATE, offset=(20, 20)))
        self.assertFalse(ui._shipyard_in_ui())

    def test_dev_control_alone_is_not_shipyard(self):
        image = self.image.copy()
        image[659:701, 33:161] = 0
        ui = self.make_ui(image)
        self.assertFalse(ui.appear(SHIPYARD_SERIES_SELECT_ENTER, offset=(20, 20)))
        self.assertTrue(ui.appear(SHIPYARD_MINUS_DEV, offset=(20, 20)))
        self.assertFalse(ui._shipyard_in_ui())

    def test_series_selection_overlay_is_not_mistaken_for_shipyard(self):
        ui = self.make_ui(self.selector_image)
        self.assertTrue(ui.appear(SHIPYARD_SERIES_SELECT_CHECK, offset=(20, 20)))
        self.assertFalse(ui._shipyard_in_ui())


if __name__ == '__main__':
    unittest.main()
