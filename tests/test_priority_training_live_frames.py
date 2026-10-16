"""Exact identity and lock checks against the 2026-10-17 CN account audit."""
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from module.os.training_ui import TrainingShipInspector


class PriorityTrainingLiveFrameTest(unittest.TestCase):
    def test_locked_tiger_and_azuchi_details(self):
        root = Path(__file__).parent / 'fixtures'
        for filename, name, level, faction, position in (
            ('priority_tiger_20261017.png', '虎', 71, '皇家', 'vanguard'),
            ('priority_azuchi_20261017.png', '安土', 70, '重樱', 'main'),
        ):
            with self.subTest(name=name):
                image = cv2.cvtColor(cv2.imread(str(root / filename)), cv2.COLOR_BGR2RGB)
                inspector = TrainingShipInspector.__new__(TrainingShipInspector)
                inspector.config = SimpleNamespace(SERVER='cn')
                inspector.device = SimpleNamespace(image=image, screenshot=lambda: None)
                inspector.appear = lambda *args, **kwargs: True
                ship = inspector.read_ship()
                self.assertEqual((ship.name, ship.level, ship.faction, ship.position),
                                 (name, level, faction, position))
                self.assertTrue(ship.is_locked)
                self.assertTrue(ship.is_rainbow)
                self.assertTrue(ship.fully_limit_broken)


if __name__ == '__main__':
    unittest.main()
