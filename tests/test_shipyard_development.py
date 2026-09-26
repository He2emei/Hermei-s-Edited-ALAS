import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from unittest.mock import patch

from module.exception import ScriptError
from module.ocr.ocr import Ocr
from module.shipyard.development_assets import (
    SUPPORTED_SIZE,
    is_task_action_label,
    normalise_cn_task_title,
    task_identity,
    task_title_area,
)
from module.shipyard.development import DevelopmentTask, ShipyardDevelopment
from module.os.training_policy import parse_training_requirement


class ShipyardDevelopmentPolicyTest(unittest.TestCase):
    def test_alert_badge_does_not_hide_second_compact_task(self):
        path = Path(__file__).parent / 'fixtures' / 'shipyard_target2_obscured.png'
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        inspector = ShipyardDevelopment.__new__(ShipyardDevelopment)
        inspector.device = SimpleNamespace(image=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        header_ys = inspector._detect_header_ys()
        self.assertEqual(header_ys, [130, 193, 257])
        self.assertEqual(inspector._task_key(inspector._ocr_task_title(193)),
                         inspector._task_key('大型技术理论I'))

    def test_live_submit_button_accepts_partial_ocr(self):
        path = Path(__file__).parent / 'fixtures' / 'shipyard_development_submit_20260923.png'
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        area = (0, 0, image.shape[1], image.shape[0])
        label = Ocr([area], lang='cnocr', name='DevelopmentSubmitEvidence').ocr(image).strip()
        self.assertEqual(label, '交')
        self.assertTrue(is_task_action_label(label))

    def test_development_action_label_rejects_unrelated_actions(self):
        for label in ('', '前往', '购买', '开始研究', '完成', '立即完成'):
            with self.subTest(label=label):
                self.assertFalse(is_task_action_label(label))

    def test_development_action_label_allows_exact_and_one_missing_glyph(self):
        for label in ('提交', '提', '交', 'SUBMIT'):
            with self.subTest(label=label):
                self.assertTrue(is_task_action_label(label))

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

    def test_stage_stroke_dropped_by_a_boundary_row_keeps_its_identity(self):
        # Live 2026-09-26 08:41: the locate sweep hunted `大型技术理论I` while
        # the row sat against the panel edge and cnocr dropped the stage
        # stroke, so the exact catalogue lookup found nothing and the task
        # aborted with `Development task is not visible`.  The identity has to
        # survive one dropped glyph, in both the recognition and the locate
        # path (both compare through `_task_key`).
        for reading, wanted in (
                ('大型技术理论', '大型技术理论I'),
                ('铁血主力技术测试', '铁血主力技术测试I'),
                ('主力技术突破', '主力技术突破I'),
                ('皇家先锋技术测试', '皇家先锋技术测试I')):
            with self.subTest(reading=reading):
                self.assertEqual(ShipyardDevelopment._task_key(reading),
                                 ShipyardDevelopment._task_key(wanted))
        # Noise must not become an identity.
        for noise in ('一7一', '-7一', '就', 'r——.———-'):
            with self.subTest(noise=noise):
                self.assertIsNone(ShipyardDevelopment._tolerant_catalog_key(noise))
                self.assertEqual(ShipyardDevelopment._task_key(noise),
                                 task_identity(noise))

    def test_one_row_seen_twice_keeps_one_identity(self):
        self.assertEqual(task_identity('菲利克斯·舒尔茨舰体塑造I143:33:43'),
                         task_identity('利克斯·舒尔茨舰体塑造143:33:43'))
        # The stage stroke is regularly lost to the countdown next to it, so both
        # stages of one ship share an identity.  Keying on the stage made the
        # inspector hunt for 舰体塑造II while the panel kept reading 舰体塑造, and
        # it aborted with "Material task is not visible" (live log 2026-09-18
        # 18:43).
        self.assertEqual(task_identity('菲利克斯·舒尔茨舰体塑造I'),
                         task_identity('利克斯·舒尔茨舰体塑造II'))
        self.assertNotEqual(task_identity('柴郡舰体塑造I'),
                            task_identity('大型技术理论I'))

    def test_live_bottom_hull_rows_remain_two_tasks_despite_stage_ocr_loss(self):
        root = Path(__file__).parents[1] / 'tests/fixtures'
        top = cv2.cvtColor(cv2.imread(str(root / 'shipyard_alas_top_rows_20260925.png')),
                           cv2.COLOR_BGR2RGB)
        bottom = cv2.cvtColor(cv2.imread(str(root / 'shipyard_alas_bottom_rows_20260925.png')),
                              cv2.COLOR_BGR2RGB)
        from types import SimpleNamespace
        obj = object.__new__(ShipyardDevelopment)
        obj.device = SimpleNamespace(image=top)
        obj._collapse_any_expanded_header = lambda: False
        obj._scroll_task_list = lambda direction=-1: setattr(obj.device, 'image',
                                                              top if direction == 1 else bottom)
        tasks = obj._read_all_tasks()
        hull = [t for t in tasks if '舰体塑' in t.title]
        self.assertEqual([(t.index, t.title[-2:], t.complete) for t in hull],
                         [(7, '造I', True), (8, 'II', False)])
        self.assertNotEqual(obj._task_key(hull[0].title), obj._task_key(hull[1].title))

    def test_live_target8_has_one_enabled_submit_action(self):
        path = Path(__file__).parents[1] / 'tests/fixtures/shipyard_alas_target8_submit_20260925.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        pixels = image[210:558, 1080:1245].astype('int16')
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        mask = ((blue > red + 45) & (blue > 140) & (green > 75)).astype('uint8') * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rects = [cv2.boundingRect(c) for c in contours]
        rects = [(x, y, w, h) for x, y, w, h in rects if w >= 100 and 25 <= h <= 65]
        self.assertEqual(len(rects), 1)
        x, y, width, height = rects[0]
        from module.shipyard.development_assets import is_task_action_label
        label = Ocr([(1080 + x, 210 + y, 1080 + x + width, 210 + y + height)],
                    lang='cnocr', name='Target8SubmitFixture').ocr(image)
        self.assertTrue(is_task_action_label(label))

    def test_expanded_target8_with_red_alert_keeps_both_hull_rows(self):
        from types import SimpleNamespace
        root = Path(__file__).parents[1] / 'tests/fixtures'
        for filename, complete in (
                ('shipyard_alas_target8_submit_20260925.png', False),
                ('shipyard_alas_target8_submitted_20260925.png', True)):
            image = cv2.cvtColor(cv2.imread(str(root / filename)), cv2.COLOR_BGR2RGB)
            obj = object.__new__(ShipyardDevelopment)
            obj.device = SimpleNamespace(image=image)
            hull = [task for task in obj._scan_visible_tasks() if '舰体塑' in task.title]
            with self.subTest(filename=filename):
                self.assertEqual([task.index for task in hull], [7, 8])
                self.assertIs(hull[1].complete, complete)

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

    def test_stage_lost_to_the_countdown_still_parses(self):
        # Live log 2026-09-17 01:53: ``铁血先锋技术测试l69:54:13`` reaches the
        # inspector as ``铁血先锋技术测试`` once the countdown is trimmed.
        title = normalise_cn_task_title('铁血先锋技术测试169:54:13')
        self.assertEqual(title, '铁血先锋技术测试')
        self.assertTrue(ShipyardDevelopment._is_technical_title(title))
        requirement = ShipyardDevelopment._parse_requirement(title)
        self.assertEqual(requirement, parse_training_requirement('铁血先锋技术测试I'))
        self.assertEqual(requirement.position, 'vanguard')

    def test_pending_requirement_accepts_a_lost_stage(self):
        tasks = [DevelopmentTask(1, normalise_cn_task_title('铁血先锋技术测试169:54:13'), False, 130)]
        self.assertEqual(ShipyardDevelopment._pending_requirement(tasks),
                         parse_training_requirement('铁血先锋技术测试I'))

    def test_ship_name_ocr_noise_does_not_abort_the_guard(self):
        from module.shipyard.development_assets import ship_name_similarity
        # Live log 2026-09-17 01:37: the working label was read back as
        # ``利克昕舒尔茨弋`` right after a header click.
        self.assertGreaterEqual(ship_name_similarity('利克昕舒尔茨弋', '菲利克斯·舒尔茨'), 0.6)
        self.assertLess(ship_name_similarity('加斯科涅', '菲利克斯·舒尔茨'), 0.6)

    def test_countdown_digits_read_as_a_han_character_stay_known(self):
        # Live log 2026-09-18 05:54: the countdown ``89:37:17`` was read as
        # ``仍:37:17``, leaving 先锋技术突破I仍 once the timer was trimmed.
        title = normalise_cn_task_title('先锋技术突破I仍:37:17')
        self.assertEqual(title, '先锋技术突破I仍')
        self.assertEqual(ShipyardDevelopment._catalog_kind(title), 'material')
        self.assertTrue(ShipyardDevelopment._is_known_material_title(title))
        self.assertEqual(ShipyardDevelopment._task_key(title),
                         ShipyardDevelopment._task_key('先锋技术突破I'))
        self.assertEqual(ShipyardDevelopment._task_key('先锋技术突破I仍'),
                         ShipyardDevelopment._task_key('先锋技术突破I89:37:17'))

    def test_stray_character_does_not_break_a_technical_row(self):
        title = normalise_cn_task_title('铁血先锋技术测试I仍:37:17')
        self.assertTrue(ShipyardDevelopment._is_technical_title(title))
        self.assertEqual(ShipyardDevelopment._parse_requirement(title),
                         parse_training_requirement('铁血先锋技术测试I'))

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

    def test_submits_available_technical_and_material_rows_even_when_marked_complete(self):
        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.config = type('Config', (), {'SERVER': 'cn'})()
                self.device = type('Device', (), {
                    'image': type('Image', (), {'shape': (720, 1280, 3)})(),
                })()
                self.pending = {'大型技术理论I', '柴郡舰体塑造I'}
                self.submitted = []

            def _scan_working_ship(self):
                return '柴郡'

            def _read_ship_name(self):
                return '柴郡'

            def _read_all_tasks(self):
                return [DevelopmentTask(1, '大型技术理论I', True, 130),
                        DevelopmentTask(2, '柴郡舰体塑造I', True, 218)]

            def _submit_available_task(self, title):
                if title not in self.pending:
                    return False
                self.pending.remove(title)
                self.submitted.append(title)
                return True

        fake = Fake()
        self.assertEqual(fake.inspect_current_project(), ('柴郡', None))
        self.assertEqual(fake.submitted, ['大型技术理论I', '柴郡舰体塑造I'])

    def test_time_locked_submit_notice_defers_without_failing_scheduler(self):
        class Device:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
                self.image[490:533, 1088:1234] = (60, 145, 230)
                self.clicks = 0
                self.history_resets = 0

            def click_record_clear(self):
                self.history_resets += 1

            def click(self, button):
                self.clicks += 1

            def sleep(self, seconds):
                pass

            def screenshot(self):
                pass

        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.device = Device()
                self.confirmed = False
                self.collapsed = False

            def _locate_visible_task(self, title):
                return DevelopmentTask(3, title, False, 243)

            def handle_popup_confirm(self, name):
                if not self.confirmed:
                    self.confirmed = True
                    return True
                return False

            def _shipyard_in_ui(self):
                return True

            def _collapse_any_expanded_header(self):
                self.collapsed = True

            def _scan_visible_tasks(self):
                raise AssertionError('The time-locked notice must be handled before task-state polling')

        readings = iter(('交', '任务还没有完成'))
        with patch('module.shipyard.development.Ocr') as ocr:
            ocr.return_value.ocr.side_effect = lambda image: next(readings)
            fake = Fake()
            self.assertFalse(fake._submit_available_task('主力技术突破I'))
        self.assertTrue(fake.collapsed)
        self.assertEqual(fake.device.clicks, 2)
        self.assertEqual(fake.device.history_resets, 1)

    def test_task_lookup_resets_from_bottom_before_searching(self):
        class Fake(ShipyardDevelopment):
            def __init__(self):
                self.position = 'bottom'
                self.swipes = []

            def _collapse_any_expanded_header(self):
                return False

            def _scroll_task_list(self, direction=-1):
                self.swipes.append(direction)
                if direction == 1:
                    self.position = 'top'

            def _detect_header_ys(self):
                return [130]

            def _scan_visible_tasks(self, header_ys=None):
                return [
                    DevelopmentTask(1, '铁血主力技术测试I' if self.position == 'top'
                                    else '主力技术突破I', False, 130)
                ]

        fake = Fake()
        result = fake._locate_visible_task('铁血主力技术测试I')
        self.assertEqual(result.header_y, 130)
        self.assertEqual(fake.swipes, [1])

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


class ShipyardDevelopmentSettledCollapseTest(unittest.TestCase):
    """The expanded-row collapse has to judge a settled frame.

    Live 2026-09-26: `_collapse_any_expanded_header()` screenshotted in the same
    instant as its click, so the row still looked expanded and the next caller
    clicked the same header a second time, which expanded it instead.  The body
    then pushed every other row out of the detection strip, and the task ended
    with `Development task is not visible` (08:14:59 and 08:21:55) - or, when the
    frame in flight held no TARGET label at all, with `Shipyard task TARGET rows
    are not identifiable` (08:16:47).
    """

    class AnimatedDevice:
        """The panel: the frame in flight right after a click, and the settled one."""

        def __init__(self, expanded, settled, in_flight):
            self.expanded = expanded
            self.settled = settled
            self.in_flight = in_flight
            self.image = expanded
            self.clicks = []
            self.sleeps = []

        def click(self, button):
            self.clicks.append(button)
            # The collapse animation has not moved the rows yet.
            self.image = self.in_flight

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            if seconds >= 0.5:
                # The animation finished while the caller waited.
                self.image = self.settled

        def screenshot(self):
            return self.image

    @staticmethod
    def fixtures():
        root = Path(__file__).parents[1] / 'tests/fixtures'
        expanded = cv2.cvtColor(cv2.imread(str(root / 'shipyard_target2_obscured.png')),
                                cv2.COLOR_BGR2RGB)
        settled = cv2.cvtColor(cv2.imread(str(root / 'shipyard_alas_top_rows_20260925.png')),
                               cv2.COLOR_BGR2RGB)
        return expanded, settled

    @staticmethod
    def inspector(device):
        obj = object.__new__(ShipyardDevelopment)
        obj.device = device
        return obj

    def test_an_expanded_row_is_collapsed_once_and_on_the_settled_frame(self):
        expanded, settled = self.fixtures()
        device = self.AnimatedDevice(expanded, settled, in_flight=expanded)
        inspector = self.inspector(device)
        self.assertTrue(inspector._collapse_any_expanded_header())
        # The next caller reads the settled frame, where the row is collapsed:
        # reading the frame in flight made it click the header a second time.
        self.assertFalse(inspector._collapse_any_expanded_header())
        self.assertEqual(len(device.clicks), 1)
        self.assertIn(0.6, device.sleeps)

    def test_the_frame_in_flight_is_never_read(self):
        expanded, settled = self.fixtures()
        in_flight = expanded.copy()
        # A collapse moves every row at once, so the strip the inspector reads
        # holds no TARGET label while it runs.
        in_flight[130:558, 944:1020] = expanded[130:558, 200:276]
        device = self.AnimatedDevice(expanded, settled, in_flight=in_flight)
        inspector = self.inspector(device)
        self.assertTrue(inspector._collapse_any_expanded_header())
        self.assertFalse(inspector._collapse_any_expanded_header())
        self.assertEqual(len(device.clicks), 1)


class ShipyardDevelopmentTaskLookupSweepTest(unittest.TestCase):
    """Locating a row has to sweep the whole, very short, scroll range.

    The CN panel keeps eight rows of 63px pitch inside a 428px viewport, so the
    scrollable range is only about one row tall and the row sitting at the
    panel boundary is partly clipped.  Live 2026-09-25 07:27 (alas2) and 10:20
    (alas), and 2026-09-26 08:41 (alas2) all ended with
    `Development task is not visible: 大型技术理论I` / `铁血主力技术测试I` for a
    row that `_read_all_tasks()` had just enumerated: the locate loop scrolled
    up twice and then only downward with a 350px swipe, so it kept reading the
    same two overlapping states while the target row stayed outside the
    readable band.
    """

    ROW_PITCH = 63
    # Two full rows of travel, so a swipe always lands on a state the previous
    # one could not reach.  The shipped value is 350, which left the viewport
    # oscillating between two states.
    SWIPE_DISTANCE = 450

    TITLES = (
        '铁血先锋技术测试I', '大型技术理论I', '先锋技术突破I', '铁血先锋技术测试II',
        '大型技术理论II', '主力技术突破I', '柴郡舰体塑造I', '柴郡舰体塑造II',
        '主力技术突破II', '先锋技术突破II', '铁血主力技术测试I', '铁血主力技术测试II',
    )

    class FakeScrollPanel:
        """A task list whose whole scrollable range is about one row tall."""

        def __init__(self, titles, top=130, bottom=558, pitch=63,
                     readable_offsets=(-63,), offset=0, top_offset=-63,
                     movable=True):
            self.titles = list(titles)
            self.top = top
            self.bottom = bottom
            self.pitch = pitch
            self.readable_offsets = tuple(readable_offsets)
            self.offset = offset
            self.top_offset = top_offset
            self.movable = movable
            self.swipes = []

        def row_y(self, index):
            return self.top + index * self.pitch

        def _readable(self, index):
            # The real panel scrolls in overlapping states a fraction of a row
            # tall, and a row pressed against the panel edge loses glyphs.  The
            # row the locate loop was hunting read as `-7一` / `一7一` in every
            # state that loop sampled, and only read in a state it never
            # reached (live 2026-09-25 07:27 alas2 / 10:20 alas, 2026-09-26
            # 08:41 alas2).
            return self.offset in self.readable_offsets

        def _title_reading(self, index):
            """What cnocr makes of the row in the current viewport state."""
            if not self._readable(index):
                return '一7一'
            # The live boundary frame dropped the stage stroke and left the
            # base title behind (live `大型技术理论` for `大型技术理论I`).
            return self.titles[index].rstrip('I') or self.titles[index]

        def _row_index(self, header_y):
            return int(round((header_y - self.top - self.offset) / float(self.pitch)))

        def _scan_visible_tasks(self, header_ys=None):
            header_ys = self._detect_header_ys() if header_ys is None else header_ys
            tasks = []
            for position, header_y in enumerate(header_ys[:8], 1):
                index = self._row_index(header_y)
                if not 0 <= index < len(self.titles):
                    continue
                tasks.append(DevelopmentTask(position, self._title_reading(index),
                                             False, header_y))
            return tasks

        def _detect_header_ys(self):
            ys = []
            for index in range(len(self.titles)):
                header_y = self.row_y(index) + self.offset
                if self.top <= header_y and header_y + 40 <= self.bottom:
                    ys.append(header_y)
            return ys

        def _ocr_task_title(self, header_y):
            index = self._row_index(header_y)
            if not 0 <= index < len(self.titles):
                return ''
            return self._title_reading(index)

        def swipe_vector(self, vector, box=None, padding=None):
            self.swipes.append(vector)

        def sleep(self, seconds):
            pass

        def screenshot(self):
            pass

        def move(self, vector):
            if not self.movable:
                return
            # The viewport cannot travel past either end of its own list.
            bottom_offset = self.top + (len(self.titles) - 1) * self.pitch - self.bottom
            self.offset = min(self.top_offset, max(bottom_offset, self.offset + vector[1]))

    @staticmethod
    def inspector(device, distance, move_step=None):
        move_step = distance if move_step is None else move_step

        class Fake(ShipyardDevelopment):
            def _collapse_any_expanded_header(self):
                return False

            def _detect_header_ys(self):
                return device._detect_header_ys()

            def _scan_visible_tasks(self, header_ys=None):
                return device._scan_visible_tasks(header_ys)

            def _ocr_task_title(self, header_y):
                return device._ocr_task_title(header_y)

            def _scroll_task_list(self, direction=-1):
                device.swipe_vector((0, direction * distance))
                device.move((0, direction * move_step))

        fake = Fake.__new__(Fake)
        fake.device = device
        return fake

    def test_lookup_reaches_the_state_that_reads(self):
        # The target row only reads cleanly in one viewport state (its header
        # at the top of the panel, with the stage stroke dropped by cnocr).
        # The sweep has to scroll into that state and stop there.
        device = self.FakeScrollPanel(self.TITLES, readable_offsets=(-63,), offset=0)
        inspector = self.inspector(device, distance=self.SWIPE_DISTANCE, move_step=90)
        task = inspector._locate_visible_task('大型技术理论I')
        self.assertEqual(task.header_y, 130)
        self.assertEqual(inspector._task_key(task.title),
                         inspector._task_key('大型技术理论I'))
        self.assertTrue(device.swipes)

    def test_a_panel_that_does_not_move_stops_instead_of_looping(self):
        # No state of this panel reads, so the sweep must give up after the
        # first swipe that fails to move the viewport instead of looping.
        device = self.FakeScrollPanel(self.TITLES, readable_offsets=(), offset=0,
                                      movable=False)
        inspector = self.inspector(device, distance=self.SWIPE_DISTANCE, move_step=90)
        with self.assertRaises(ScriptError):
            inspector._locate_visible_task('大型技术理论I')
        self.assertEqual(len(device.swipes), 1)


class ShipyardDevelopmentRealFrameLocateTest(unittest.TestCase):
    """The sweep has to work on the real CN panel geometry."""

    class ScrollingPanel:
        def __init__(self, image):
            self.source = image
            self.offset = 0
            self.image = image
            self.render()
            self.swipes = []

        def render(self):
            out = self.source.copy()
            top, bottom = 130, 558
            out[top:bottom, 940:1280] = self.source[top + self.offset:bottom + self.offset, 940:1280]
            self.image = out

        def swipe_vector(self, vector, box=None, padding=None):
            self.swipes.append(vector)

        def move(self, vector):
            self.offset = max(-160, min(160, self.offset + vector[1]))
            self.render()

        def sleep(self, seconds):
            pass

        def screenshot(self):
            pass

        def click(self, button):
            raise AssertionError('the live frame needs no collapse click')

    def test_live_panel_row_is_located_through_the_sweep(self):
        root = Path(__file__).parents[1] / 'tests/fixtures'
        image = cv2.cvtColor(cv2.imread(str(root / 'shipyard_alas_top_rows_20260925.png')),
                             cv2.COLOR_BGR2RGB)
        device = self.ScrollingPanel(image)
        inspector = object.__new__(ShipyardDevelopment)
        inspector.device = device
        task = inspector._locate_visible_task('大型技术理论I')
        self.assertEqual(inspector._task_key(task.title),
                         inspector._task_key('大型技术理论I'))
        self.assertIn(task.header_y, range(130, 559))


if __name__ == '__main__':
    unittest.main()
