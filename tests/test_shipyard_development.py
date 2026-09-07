import unittest
from pathlib import Path

import cv2

from module.exception import ScriptError
from module.ocr.ocr import Ocr
from module.shipyard.development_assets import SUPPORTED_SIZE, task_title_area
from module.shipyard.development import DevelopmentTask, ShipyardDevelopment
from module.os.training_policy import parse_training_requirement


class ShipyardDevelopmentPolicyTest(unittest.TestCase):
    def test_requires_cn_1280x720_before_device_work(self):
        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.device = type('Device', (), {'image': type('Image', (), {'shape': (1080, 1920, 3)})()})()

        with self.assertRaises(ScriptError):
            Fake().inspect_current_project()

    def test_task_one_is_selected_before_task_two(self):
        tasks = [
            DevelopmentTask(1, '皇家先锋技术测试I', False, 130),
            DevelopmentTask(4, '皇家先锋技术测试II', False, 340),
        ]
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('皇家先锋技术测试I'))

    def test_task_two_requires_completed_task_one(self):
        tasks = [
            DevelopmentTask(1, '皇家先锋技术测试I', True, 130),
            DevelopmentTask(4, '皇家先锋技术测试II', False, 340),
        ]
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('皇家先锋技术测试II'))

    def test_task_two_without_completed_prerequisite_is_not_used(self):
        tasks = [DevelopmentTask(4, '皇家先锋技术测试II', False, 340)]
        with self.assertRaises(ScriptError):
            ShipyardDevelopment._pending_requirement(tasks)

    def test_second_stage_uses_its_own_faction_and_position(self):
        tasks = [DevelopmentTask(1, '皇家先锋技术测试I', True, 130),
                 DevelopmentTask(4, '白鹰主力技术测试II', False, 340)]
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('白鹰主力技术测试II'))

    def test_no_pending_technical_task_returns_none(self):
        tasks = [
            DevelopmentTask(1, '皇家先锋技术测试I', True, 130),
            DevelopmentTask(4, '皇家先锋技术测试II', True, 340),
        ]
        self.assertIsNone(ShipyardDevelopment._pending_requirement(tasks))

    def test_unknown_task_is_not_misclassified_as_technical(self):
        self.assertFalse(ShipyardDevelopment._is_technical_title('未知任务'))

    def test_material_titles_are_exact_and_completed_unknown_can_be_skipped(self):
        self.assertFalse(ShipyardDevelopment._is_known_material_title('大型技术理论I'))
        self.assertTrue(ShipyardDevelopment._is_known_material_title('先锋技术突破Ⅱ'))
        self.assertTrue(ShipyardDevelopment._is_known_material_title('柴郡舰体塑造I'))
        self.assertTrue(ShipyardDevelopment._is_known_material_title('柴郡舰体塑造II'))
        self.assertFalse(ShipyardDevelopment._is_known_material_title('大型技术理论I其他'))
        self.assertFalse(ShipyardDevelopment._is_known_material_title('经验材料'))

    def test_header_scan_uses_relocated_rows(self):
        class Fake(ShipyardDevelopment):
            def _detect_header_ys(self):
                return [130, 218, 282, 346, 408, 472, 535]

            def _ocr_task_title(self, header_y):
                return {
                    130: '大型技术理论I', 218: '皇家先锋技术测试I',
                    282: '先锋技术突破I', 346: '皇家先锋技术测试II',
                }.get(header_y, '')

            def _task_complete(self, header_y):
                return header_y in (218, 282)

        fake = Fake.__new__(Fake)
        tasks = fake._scan_visible_tasks()
        self.assertEqual([task.header_y for task in tasks], [130, 218, 282, 346])
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('皇家先锋技术测试II'))

    def test_read_only_inspection_does_not_click_completed_material(self):
        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.config = type('Config', (), {'SERVER': 'cn'})()
                self.device = type('Device', (), {
                    'image': type('Image', (), {'shape': (720, 1280, 3)})(),
                })()
                self.submitted = False

            def _scan_working_ship(self):
                return '柴郡'

            def _read_all_tasks(self):
                return [
                    DevelopmentTask(1, '大型技术理论I', True, 130),
                    DevelopmentTask(2, '皇家先锋技术测试I', False, 218),
                ]

            def _submit_material_task(self, title):
                self.submitted = True

        fake = Fake()
        ship, requirement = fake.inspect_current_project(submit_materials=False)
        self.assertEqual(ship, '柴郡')
        self.assertEqual(requirement, parse_training_requirement('皇家先锋技术测试I'))
        self.assertFalse(fake.submitted)

    def test_unknown_incomplete_material_is_rejected(self):
        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.config = type('Config', (), {'SERVER': 'cn'})()
                self.device = type('Device', (), {
                    'image': type('Image', (), {'shape': (720, 1280, 3)})(),
                })()

            def _scan_working_ship(self):
                return '柴郡'

            def _read_all_tasks(self):
                return [DevelopmentTask(1, '未知材料任务', False, 130)]

        with self.assertRaises(ScriptError):
            Fake().inspect_current_project(submit_materials=True)

    def test_real_cn_evidence_has_supported_size_and_ocr_pipeline(self):
        path = Path(__file__).parents[2] / 'code_workflow' / 'evidence' / '2026-09-08' / 'shipyard.png'
        if not path.exists():
            self.skipTest('shipyard evidence is not present in this checkout')
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        self.assertEqual((image.shape[1], image.shape[0]), SUPPORTED_SIZE)
        text = Ocr([task_title_area(130)], lang='cnocr', name='SHIPYARD_EVIDENCE_TEST').ocr(image[:, :, :3])
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip())
        from types import SimpleNamespace
        obj = object.__new__(ShipyardDevelopment)
        obj.device = SimpleNamespace(image=image)
        tasks = obj._scan_visible_tasks()
        technical = [t for t in tasks if obj._is_technical_title(t.title)]
        self.assertEqual([t.title for t in technical], ['皇家先锋技术测试I', '皇家先锋技术测试II'])
        self.assertFalse(any(t.complete for t in technical))
        self.assertTrue(all(t.complete for t in tasks if t not in technical))
        self.assertEqual(obj._pending_requirement(tasks), parse_training_requirement('皇家先锋技术测试I'))


if __name__ == '__main__':
    unittest.main()
