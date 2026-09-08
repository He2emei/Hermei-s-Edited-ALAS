import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

import module.config.server as server
from module.map.assets import MAP_PREPARATION, MAP_PREPARATION_HARD
from module.map.map_operation import MapOperation


FIXTURES = Path(__file__).parent / 'fixtures' / 'map_preparation'


class MapPreparationTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'cn'

    def tearDown(self):
        server.server = self._server

    def operation(self, filename, server_name='cn'):
        image_path = Path(filename)
        if not image_path.is_absolute() and not image_path.exists():
            image_path = FIXTURES / image_path
        operation = MapOperation.__new__(MapOperation)
        operation.config = SimpleNamespace(
            SERVER=server_name,
            MAP_HAS_CLEAR_PERCENTAGE=False,
        )
        operation.device = SimpleNamespace(
            image=np.array(Image.open(image_path).convert('RGB')),
            stuck_record_add=lambda button: None,
        )
        operation.interval_timer = {}
        operation.map_clear_percentage_prev = -1
        operation.map_clear_percentage_timer = MapOperation.map_clear_percentage_timer
        return operation

    def test_cn_2_4_dialog_uses_color_fallback_when_default_match_misses(self):
        operation = self.operation('2-4-dialog.png')

        self.assertFalse(operation.appear(MAP_PREPARATION, offset=(20, 20)))
        self.assertTrue(operation.match_template_color(
            MAP_PREPARATION, offset=(20, 20), similarity=0.8))
        self.assertIs(operation.handle_map_preparation(), MAP_PREPARATION)

    def test_other_pages_are_rejected(self):
        for filename in ('chapter2.png', 'home.png', 'campaign-menu.png', 'start.png'):
            with self.subTest(filename=filename):
                self.assertIsNone(self.operation(filename).handle_map_preparation())

    def test_existing_normal_and_hard_detection_remains_available(self):
        normal = self.operation('./assets/cn/map/MAP_PREPARATION.png')
        self.assertIs(normal.handle_map_preparation(), MAP_PREPARATION)

        hard = self.operation('./assets/cn/map/MAP_PREPARATION_HARD.png')
        self.assertIs(hard.handle_map_preparation(), MAP_PREPARATION_HARD)

    def test_color_mismatch_rejects_same_luma_pattern(self):
        operation = self.operation('2-4-dialog.png')
        image = operation.device.image.copy()
        image[497:525, 975:1094] = image[497:525, 975:1094][:, :, ::-1]
        operation.device.image = image
        self.assertTrue(MAP_PREPARATION.match_luma(image, offset=(20, 20), similarity=0.8))
        self.assertFalse(operation.match_template_color(
            MAP_PREPARATION, offset=(20, 20), similarity=0.8))
        self.assertIsNone(operation.handle_map_preparation())

    def test_color_fallback_is_cn_only(self):
        operation = self.operation('2-4-dialog.png', server_name='en')
        server.server = 'en'
        self.assertIsNone(operation.handle_map_preparation())


if __name__ == '__main__':
    unittest.main()
