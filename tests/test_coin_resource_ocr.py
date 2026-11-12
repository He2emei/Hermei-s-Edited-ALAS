import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from module.reward.coin_resource import (
    OCR_COIN_STORAGE_CURRENT,
    OCR_COIN_STORAGE_CURRENT_CN,
    read_coin_storage,
)


FIXTURES = Path(__file__).parent / 'fixtures' / 'coin_resource'


def home_image(current_name, limit_name='cn-limit-96900.png'):
    """Rebuild only the two numeric ROIs on a blank-sized game canvas."""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    current = cv2.cvtColor(
        cv2.imread(str(FIXTURES / current_name)), cv2.COLOR_BGR2RGB)
    limit = cv2.cvtColor(
        cv2.imread(str(FIXTURES / limit_name)), cv2.COLOR_BGR2RGB)
    image[24:49, 716:780] = current
    image[0:22, 738:781] = limit
    return image


class CoinResourceOcrTest(unittest.TestCase):
    @patch('module.reward.coin_resource.server')
    def test_cn_reads_all_three_moving_background_frames(self, config_server):
        config_server.server = 'cn'
        for index in range(3):
            with self.subTest(frame=index):
                self.assertEqual(
                    read_coin_storage(home_image(f'cn-current-277041-{index}.png')),
                    (277041, 96900),
                )

    @patch('module.reward.coin_resource.server')
    def test_cn_reader_covers_other_live_balances(self, config_server):
        config_server.server = 'cn'
        expected = {
            'cn-current-79747.png': (79747, 'cn-limit-95700.png', 95700),
            'cn-current-141737.png': (141737, 'cn-limit-95700.png', 95700),
            'cn-current-283343.png': (283343, 'cn-limit-96900.png', 96900),
            'cn-current-245645.png': (245645, 'cn-limit-96900.png', 96900),
        }
        for fixture, (current, limit_fixture, limit) in expected.items():
            with self.subTest(fixture=fixture):
                self.assertEqual(
                    read_coin_storage(home_image(fixture, limit_fixture)),
                    (current, limit),
                )

    @patch('module.reward.coin_resource.server')
    def test_non_cn_keeps_existing_current_reader(self, config_server):
        config_server.server = 'en'
        with patch.object(OCR_COIN_STORAGE_CURRENT, 'ocr', return_value=12345) as old_reader, \
                patch.object(OCR_COIN_STORAGE_CURRENT_CN, 'ocr') as cn_reader, \
                patch('module.reward.coin_resource.OCR_COIN_STORAGE_LIMIT.ocr', return_value=94200):
            self.assertEqual(read_coin_storage(np.zeros((720, 1280, 3), dtype=np.uint8)),
                             (12345, 94200))
        old_reader.assert_called_once()
        cn_reader.assert_not_called()

    @patch('module.reward.coin_resource.server')
    def test_blank_unknown_frame_does_not_invent_a_balance(self, config_server):
        config_server.server = 'cn'
        self.assertEqual(
            read_coin_storage(np.zeros((720, 1280, 3), dtype=np.uint8)),
            (0, 0),
        )


if __name__ == '__main__':
    unittest.main()
