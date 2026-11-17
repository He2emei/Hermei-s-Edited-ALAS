import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import RequestHumanTakeover
from module.os import training_ui


ROOT = Path(__file__).parents[1]


def numeric_frame():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    crop = np.asarray(Image.open(ROOT / 'tests/fixtures/opsi_training/mogador105-normal-exp-crop.png').convert('RGB'))
    assert crop.shape == (27, 118, 3)
    image[281:308, 1130:1248] = crop
    return image


class NumericExpSplitTest(unittest.TestCase):
    def test_real_numeric_crop_reads_both_numbers(self):
        self.assertEqual(training_ui._read_split_current_exp(numeric_frame()), (29290, 78000))

    def test_unknown_clipped_conflicting_or_invalid_numbers_are_rejected(self):
        for readings in (
                ['29290', '8000', '29290', '8000'],
                ['29290', '78000', '29299', '78000'],
                ['29290', '78000', '29290', '79000'],
                ['29290Z', '78000', '29290Z', '78000'],
                ['29290', 'M8X', '29290', 'M8X'],
                ['78000', '78000', '78000', '78000'],
                ['80000', '78000', '80000', '78000'],
                ['-1', '78000', '-1', '78000'],
                [True, '78000', True, '78000'],
                ['29290', '', '29290', ''],
                ['29290', '174000', '29290', '174000']):
            with self.subTest(readings=readings), \
                    patch.object(training_ui, '_read_exact_stored_exp_max', return_value=False), \
                    patch.object(training_ui, 'Ocr') as ocr:
                ocr.return_value.ocr.side_effect = readings
                self.assertIsNone(training_ui._read_split_current_exp(numeric_frame()))

    def test_exact_max_does_not_use_numeric_recovery(self):
        with patch.object(training_ui, '_read_exact_stored_exp_max', return_value=True), \
                patch.object(training_ui, 'Ocr') as ocr:
            self.assertIsNone(training_ui._read_split_current_exp(numeric_frame()))
            ocr.assert_not_called()

    def inspect(self, level=105, locked=True):
        frame = np.asarray(Image.open(ROOT / 'tests/fixtures/opsi_training/tiger-105-post-awakening-exp-noise.png').convert('RGB')).copy()
        frame[281:308, 1130:1248] = numeric_frame()[281:308, 1130:1248]
        inspector = training_ui.TrainingShipInspector.__new__(training_ui.TrainingShipInspector)
        inspector.config = SimpleNamespace(SERVER='cn')
        inspector.device = SimpleNamespace(image=frame, screenshot=Mock())
        inspector.appear = Mock(return_value=True)
        real_ocr = training_ui.Ocr
        def reader(buttons, **kwargs):
            if kwargs.get('name') == 'TrainingName':
                return SimpleNamespace(ocr=lambda image: ['虎', '虎'])
            return real_ocr(buttons, **kwargs)
        with patch.object(training_ui, 'Ocr', side_effect=reader), \
                patch.object(training_ui, 'detail_ship_lock', return_value=locked), \
                patch.object(training_ui, 'Digit') as digit:
            digit.return_value.ocr.return_value = level
            return inspector.read_ship()

    def test_two_frame_reader_preserves_numeric_not_stored_semantics(self):
        ship = self.inspect()
        self.assertEqual((ship.name, ship.level, ship.level_cap, ship.is_locked), ('虎', 105, 110, True))
        self.assertIsNone(ship.stored_exp)

    def test_numeric_recovery_does_not_open_level_125_or_unknown_lock(self):
        for arguments in ({'level': 125}, {'locked': None}):
            with self.subTest(arguments=arguments), self.assertRaises(RequestHumanTakeover):
                self.inspect(**arguments)


if __name__ == '__main__':
    unittest.main()
