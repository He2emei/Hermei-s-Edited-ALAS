import unittest
from pathlib import Path

import cv2

from module.exception import ScriptError
from module.ocr.ocr import Ocr
from module.shipyard.development_assets import (
    SUPPORTED_SIZE,
    normalise_cn_task_title,
    task_identity,
    task_title_area,
)
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

    def test_countdown_printed_on_the_title_line_is_removed(self):
        # Live CN development panel, 2026-09-16: every locked row prints its
        # countdown on the title line, right-aligned, and the longest titles
        # run straight into it without a separator.
        observed = {
            '大型技术理论I23:33:43': '大型技术理论I',
            '先锋技术突破I47:33:43': '先锋技术突破I',
            '铁血先锋技术测试II71:33:43': '铁血先锋技术测试II',
            '大型技术理论II95:33:43': '大型技术理论II',
            '先锋技术突破‖119:33:43': '先锋技术突破II',
            '菲利克斯·舒尔茨舰体塑造143:33:43': '菲利克斯·舒尔茨舰体塑造',
            '大型技术理论l23:54:44': '大型技术理论I',
            '先锋技术突破I:54:43': '先锋技术突破I',
            '铁血先锋技术测试ll1:54:43': '铁血先锋技术测试II',
            '利克斯·舒尔茨舰体塑造|143:54:43': '利克斯·舒尔茨舰体塑造I',
            '柴郡舰体塑造I': '柴郡舰体塑造I',
            '铁血先锋技术测试I': '铁血先锋技术测试I',
        }
        for raw, expected in observed.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalise_cn_task_title(raw), expected)

    def test_locked_technical_rows_still_produce_a_requirement(self):
        tasks = [
            DevelopmentTask(1, normalise_cn_task_title('铁血先锋技术测试I'), True, 130),
            DevelopmentTask(4, normalise_cn_task_title('铁血先锋技术测试II95:33:43'), False, 340),
        ]
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('铁血先锋技术测试II'))

    def test_ship_missing_from_the_catalog_is_still_hull_material(self):
        # 菲利克斯·舒尔茨 was released after the 2026-09-08 catalog snapshot.
        self.assertTrue(ShipyardDevelopment._is_known_material_title('菲利克斯·舒尔茨舰体塑造'))
        self.assertTrue(ShipyardDevelopment._is_known_material_title('菲利克斯·舒尔茨舰体塑造I'))
        self.assertFalse(ShipyardDevelopment._is_known_material_title('菲利克斯·舒尔茨'))

    def test_stage_swallowed_by_the_countdown_stays_known(self):
        # A locked 先锋技术突破I can lose its stage stroke to the countdown digits.
        self.assertEqual(ShipyardDevelopment._catalog_kind('先锋技术突破'), 'material')
        self.assertTrue(ShipyardDevelopment._is_known_material_title('先锋技术突破'))
        self.assertIsNone(ShipyardDevelopment._catalog_kind('菲利克斯·舒尔茨'))

    def test_one_row_seen_twice_keeps_one_identity(self):
        self.assertEqual(task_identity('菲利克斯·舒尔茨舰体塑造I143:33:43'),
                         task_identity('利克斯·舒尔茨舰体塑造143:33:43'))
        self.assertNotEqual(task_identity('菲利克斯·舒尔茨舰体塑造I'),
                            task_identity('菲利克斯·舒尔茨舰体塑造II'))

    def test_locked_rows_from_live_evidence_carry_no_countdown(self):
        path = (Path(__file__).parents[2] / 'code_workflow' / 'evidence' / '2026-09-16'
                / 'shipyard-alas-locked-timer.png')
        if not path.exists():
            self.skipTest('2026-09-16 locked-row evidence is not present in this checkout')
        from types import SimpleNamespace
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        self.assertEqual((image.shape[1], image.shape[0]), SUPPORTED_SIZE)
        obj = object.__new__(ShipyardDevelopment)
        obj.device = SimpleNamespace(image=image)
        titles = [task.title for task in obj._scan_visible_tasks()]
        self.assertIn('大型技术理论I', titles)
        self.assertIn('铁血先锋技术测试I', titles)
        # The longest title loses a stroke to the countdown, so only the
        # hull-sculpting anchor is asserted here.
        self.assertTrue(any('舰体塑' in title for title in titles))
        self.assertFalse(any(':' in title or any(char.isdigit() for char in title)
                             for title in titles))
        self.assertTrue(any(ShipyardDevelopment._is_known_material_title(title)
                            for title in titles))

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
