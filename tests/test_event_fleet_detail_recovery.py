import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.event.fleet_preparation import EventFleetPreparation
from module.exception import RequestHumanTakeover

FIXTURES = Path(__file__).parent / 'fixtures' / 'event_fleet'


def frame(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


class EventFleetDetailRecoveryTest(unittest.TestCase):
    def prepare(self, outcomes):
        prep = object.__new__(EventFleetPreparation)
        start = frame('prep-alas2-c1.png')
        states = iter(outcomes)
        device = SimpleNamespace(image=start, screenshot=Mock(), sleep=Mock(),
                                 stuck_record_add=Mock())
        device.long_click = Mock(side_effect=lambda *args, **kwargs:
                                 setattr(device, 'image', next(states)))
        device.click = Mock(side_effect=lambda *args, **kwargs:
                            setattr(device, 'image', start))
        prep.device = device
        return prep

    def test_real_unselected_dock_is_cancelled_before_retrying_detail_inspection(self):
        prep = self.prepare([frame('alas-long-press-selection.png'),
                             frame('detail-calibration.png')])
        with patch('module.event.fleet_preparation.Ocr') as ocr, \
                patch('module.event.fleet_preparation.EventFleetNameOcr') as color, \
                patch('module.event.fleet_preparation.Digit') as digit:
            ocr.return_value.ocr.return_value = ['卡辛'] * 3
            color.return_value.ocr.return_value = ['卡辛'] * 3
            digit.return_value.ocr.return_value = 100
            self.assertEqual(prep._read_slot(3), {'name': '卡辛', 'level': 100})
        self.assertEqual(prep.device.long_click.call_count, 2)
        self.assertEqual(prep.device.click.call_count, 2)  # Cancel then detail Back.
        self.assertTrue(prep._at_preparation())

    def test_repeated_selection_misfire_is_bounded_and_leaves_preparation(self):
        prep = self.prepare([frame('alas-long-press-selection.png')] * 3)
        with self.assertRaises(RequestHumanTakeover):
            prep._read_slot(7)
        self.assertEqual(prep.device.long_click.call_count, 3)
        self.assertEqual(prep.device.click.call_count, 3)
        self.assertTrue(prep._at_preparation())

    def test_unknown_page_is_never_cancelled_or_retried(self):
        prep = self.prepare([np.zeros((720, 1280, 3), dtype='uint8')])
        with self.assertRaises(RequestHumanTakeover):
            prep._read_slot(7)
        prep.device.click.assert_not_called()
        self.assertEqual(prep.device.long_click.call_count, 1)

    def test_dock_with_selected_ship_is_never_changed(self):
        prep = self.prepare([frame('alas-long-press-selection.png')])
        with patch('module.event.fleet_preparation.OCR_DOCK_SELECTED.ocr',
                   return_value=(1, 0, 1)):
            with self.assertRaises(RequestHumanTakeover):
                prep._read_slot(7)
        prep.device.click.assert_not_called()
        self.assertEqual(prep.device.long_click.call_count, 1)


if __name__ == '__main__':
    unittest.main()
