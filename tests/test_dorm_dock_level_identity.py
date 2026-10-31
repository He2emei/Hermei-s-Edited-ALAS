import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.dorm.training import DormTraining
from module.exception import RequestHumanTakeover


FRAME = Path(__file__).parent / 'fixtures/dorm_training/u410-105-regular-dock.png'
LOW_LEVEL_FRAME = Path(__file__).parent / 'fixtures/dorm_training/dorm-fault-current.png'


class DormDockLevelIdentityTests(unittest.TestCase):
    def scan(self, image, target):
        app = DormTraining.__new__(DormTraining)
        app.device = Mock(image=image)
        with patch('module.dorm.training.DORM_SCROLL') as scroll:
            scroll.at_bottom.return_value = True
            return app._scan_selection(target)

    def test_real_locked_u410_105_is_found_without_changing_target_level(self):
        image = np.asarray(Image.open(FRAME).convert('RGB'))
        target = SimpleNamespace(name='U-410', level=105)
        card = self.scan(image, target)
        self.assertGreater(card.area[0], 1000)
        self.assertEqual(target.level, 105)

    def test_same_card_is_not_mistaken_for_level_15(self):
        image = np.asarray(Image.open(FRAME).convert('RGB'))
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-410', level=15))

    def test_other_visible_card_keeps_its_measured_level(self):
        image = np.asarray(Image.open(FRAME).convert('RGB'))
        card = self.scan(image, SimpleNamespace(name='U-96', level=125))
        self.assertEqual(card.area[0], 258)

    def test_unreadable_target_level_fails_closed(self):
        image = np.asarray(Image.open(FRAME).convert('RGB')).copy()
        # Obscure only U-410's level digits; its name and card remain identifiable.
        image[308:331, 1171:1219] = (0, 0, 0)
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-410', level=105))

    def test_real_low_level_u522_remains_at_88_and_rejects_high_level(self):
        image = np.asarray(Image.open(LOW_LEVEL_FRAME).convert('RGB'))
        card = self.scan(image, SimpleNamespace(name='U-522', level=88))
        self.assertEqual(card.area[0], 587)
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-522', level=100))

if __name__ == '__main__':
    unittest.main()
