import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.dorm.training import DormTraining
from module.exception import RequestHumanTakeover
from module.ocr.ocr import Digit


FRAME = Path(__file__).parent / 'fixtures/dorm_training/u410-105-regular-dock.png'
LOW_LEVEL_FRAME = Path(__file__).parent / 'fixtures/dorm_training/dorm-fault-current.png'
U410_110_LEVEL = Path(__file__).parent / 'fixtures/dorm_training/dock-level-u410-110.png'
U410_10_LEVEL = Path(__file__).parent / 'fixtures/dorm_training/dock-level-u410-10.png'


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

    def test_real_level_110_banner_is_found_by_native_selection_scan(self):
        # Place only the anonymous live level banner in the existing dock frame.
        # The native card/name/level OCR path must find 110 and reject 10.
        image = np.asarray(Image.open(FRAME).convert('RGB')).copy()
        banner = np.asarray(Image.open(U410_110_LEVEL).convert('RGB'))
        self.assertEqual(banner.shape, (25, 74, 3))
        image[307:332, 1145:1219] = banner
        card = self.scan(image, SimpleNamespace(name='U-410', level=110))
        self.assertEqual(card.area, (1081, 303, 1219, 507))
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-410', level=10))

    def test_cropped_regular_dock_banner_reads_u410_level_110(self):
        image = np.asarray(Image.open(U410_110_LEVEL).convert('RGB'))
        level = Digit([(0, 0, image.shape[1], image.shape[0])], letter=(255, 255, 255),
                      threshold=90, alphabet='0123456789').ocr(image)
        self.assertEqual(level, 110)

    def test_cropped_regular_dock_banner_reads_u410_level_10(self):
        image = np.asarray(Image.open(U410_10_LEVEL).convert('RGB'))
        level = Digit([(0, 0, image.shape[1], image.shape[0])], letter=(255, 255, 255),
                      threshold=90, alphabet='0123456789').ocr(image)
        self.assertEqual(level, 10)

    def test_prefix_stripped_target_uses_expanded_exact_name_read(self):
        card = SimpleNamespace(area=(1081, 303, 1219, 507))
        app = DormTraining.__new__(DormTraining)
        app.device = Mock(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        with patch('module.dorm.training.dock_cards', return_value=[card]), \
                patch('module.dorm.training.Ocr', side_effect=[
                    Mock(ocr=Mock(return_value=['U-410'])),
                    Mock(ocr=Mock(return_value=['U-410'])),
                ]), \
                patch('module.dorm.training.LevelOcr', return_value=Mock(ocr=Mock(return_value=[10]))), \
                patch('module.dorm.training.Digit', side_effect=[
                    Mock(ocr=Mock(return_value=[11])),
                    Mock(ocr=Mock(return_value=110)),
                ]) as digit:
            with patch('module.dorm.training.DORM_SCROLL') as scroll:
                scroll.at_bottom.return_value = True
                result = app._scan_selection(SimpleNamespace(name='U-410', level=110))
        self.assertIs(result, card)
        self.assertEqual(digit.call_args_list[-1][0][0], [(1145, 307, 1219, 332)])

    def test_expanded_read_does_not_promote_real_level_10_to_110(self):
        card = SimpleNamespace(area=(1081, 303, 1219, 507))
        app = DormTraining.__new__(DormTraining)
        app.device = Mock(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        with patch('module.dorm.training.dock_cards', return_value=[card]), \
                patch('module.dorm.training.Ocr', side_effect=[
                    Mock(ocr=Mock(return_value=['U-410'])),
                    Mock(ocr=Mock(return_value=['U-410'])),
                ]), \
                patch('module.dorm.training.LevelOcr', return_value=Mock(ocr=Mock(return_value=[10]))), \
                patch('module.dorm.training.Digit', side_effect=[
                    Mock(ocr=Mock(return_value=[11])),
                    Mock(ocr=Mock(return_value=10)),
                ]):
            with patch('module.dorm.training.DORM_SCROLL') as scroll:
                scroll.at_bottom.return_value = True
                with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
                    app._scan_selection(SimpleNamespace(name='U-410', level=110))

    def test_same_card_is_not_mistaken_for_level_15(self):
        image = np.asarray(Image.open(FRAME).convert('RGB'))
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-410', level=15))
        with self.assertRaisesRegex(RequestHumanTakeover, 'Submarine not available'):
            self.scan(image, SimpleNamespace(name='U-410', level=10))

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
