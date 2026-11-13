import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from module.base.button import Button
from module.combat.level import LevelOcr
from module.os.training import TrainingFleetManager
from module.os.training_policy import ShipCandidate


ROOT = Path(__file__).resolve().parent
ANONYMOUS_LEVEL_CROP = ROOT / 'fixtures/opsi_training/deployment_level_1001_edge.png'


class TrainingDeploymentLevelBorderTest(unittest.TestCase):
    def manager(self):
        manager = object.__new__(TrainingFleetManager)
        manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                         screenshot=lambda: None, sleep=lambda *_: None,
                                         click_record_clear=lambda: None)
        manager._visible_cards = [Button((422, 303, 560, 507), (0, 0, 0),
                                         (422, 303, 560, 507), name='fixture')]
        return manager

    def test_anonymous_real_crop_reads_level_100(self):
        image = cv2.cvtColor(cv2.imread(str(ANONYMOUS_LEVEL_CROP)), cv2.COLOR_BGR2RGB)
        self.assertEqual(image.shape[:2], (22, 61))
        self.assertEqual(LevelOcr([(0, 0, 61, 22)], name='DeploymentLevelCropFixture').ocr(image), 1001)
        self.assertEqual(LevelOcr([(0, 0, 59, 22)], name='DeploymentLevelCropFixtureTight').ocr(image), 100)
        cards = [Button((-77, -5, 61, 199), (0, 0, 0), (-77, -5, 61, 199), name=f'card-{i}')
                 for i in range(2)]
        manager = self.manager()
        manager.device.image = image
        self.assertEqual(manager._deployment_card_levels(cards), [100, 100])

    def test_all_valid_boundary_levels_do_not_retry(self):
        manager = self.manager()
        with patch('module.os.training.LevelOcr') as ocr:
            ocr.return_value.ocr.return_value = [0, 1, 10, 75, 100, 120, 125]
            cards = manager._visible_cards * 7
            self.assertEqual(manager._deployment_card_levels(cards), [0, 1, 10, 75, 100, 120, 125])
            ocr.assert_called_once()

    def test_1001_retries_and_accepts_only_consistent_100(self):
        manager = self.manager()
        areas = []
        outputs = iter(([1001], 100, 100))

        def make_ocr(boxes, **kwargs):
            areas.append(boxes)
            value = next(outputs)
            return SimpleNamespace(ocr=lambda _: value)

        with patch('module.os.training.LevelOcr', side_effect=make_ocr):
            self.assertEqual(manager._deployment_card_levels(manager._visible_cards), [100])
        self.assertEqual(areas, [[(499, 308, 560, 330)], [(499, 308, 558, 330)],
                                 [(499, 308, 554, 330)]])

    def test_inconsistent_or_out_of_range_retry_keeps_original(self):
        for readings in ((100, 99), (99, 99), (126, 126)):
            with self.subTest(readings=readings):
                manager = self.manager()
                values = [SimpleNamespace(ocr=lambda _: [1001])]
                values.extend(SimpleNamespace(ocr=lambda _, value=value: value) for value in readings)
                with patch('module.os.training.LevelOcr', side_effect=values):
                    self.assertEqual(manager._deployment_card_levels(manager._visible_cards), [1001])

    def test_scan_and_relocation_paths_use_shared_reader(self):
        manager = self.manager()
        manager._visible_names = lambda: ['fixture-ship']
        manager._raw_names = ['fixture-ship']
        manager.device.image[:] = 0
        target = ShipCandidate('fixture-ship', '铁血', 'submarine', 100, False, True, 0, 120, True)
        with patch('module.os.training.DOCK_SCROLL.set_top'), \
                patch('module.os.training.DOCK_SCROLL.cal_position', return_value=1.0), \
                patch('module.os.training.dock_card_lock', return_value=True), \
                patch('module.os.training.same_card_portrait', return_value=False), \
                patch.object(manager, '_deployment_card_levels', return_value=[100]) as reader:
            self.assertIs(manager._scan_selection(target), manager._visible_cards[0])
            self.assertEqual(reader.call_count, 2)  # initial scan and sole-card relocation
            reader.assert_called_with(manager._visible_cards)

        manager = self.manager()
        manager._visible_names = lambda: ['fixture-ship']
        with patch('module.os.training.DOCK_SCROLL.set_top'), \
                patch('module.os.training.DOCK_SCROLL.cal_position', return_value=1.0), \
                patch('module.os.training.dock_card_lock', return_value=True), \
                patch.object(manager, '_deployment_card_levels', return_value=[100]) as reader:
            self.assertIs(manager._locate_verified_locked_card(target), manager._visible_cards[0])
            reader.assert_called_once_with(manager._visible_cards)


if __name__ == '__main__':
    unittest.main()
