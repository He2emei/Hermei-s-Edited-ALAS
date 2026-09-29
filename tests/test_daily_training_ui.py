import unittest
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import collections

from module.dorm.training import DormTraining, maintain_dorm_if_due
from module.exception import RequestHumanTakeover
from module.exception import GameTooManyClickError
from module.os.training_policy import ShipCandidate
from module.storage.training_inventory import ITEM_NAMES, TrainingInventory, item_position, parse_owned_count


def submarine(name='U-test', level=90, cap=None):
    return ShipCandidate(name, '皇家', 'submarine', level, False, True, None, cap)


class DormTrainingMockTest(unittest.TestCase):
    def _runner(self, current=None, capacity=1):
        runner = DormTraining.__new__(DormTraining)
        runner.config = SimpleNamespace(SERVER='cn')
        runner.device = SimpleNamespace(
            image=SimpleNamespace(shape=(720, 1280)),
            screenshot=Mock(),
            sleep=Mock(),
            click=Mock(),
        )
        runner._check_cn = Mock()
        runner.inspect_roster = Mock(return_value=(current or {1: None}, capacity))
        runner._open_training = Mock()
        runner._open_selection = Mock()
        runner._close_training = Mock()
        runner._training_visible = Mock(return_value=True)
        runner._scan_selection = Mock(return_value=set())
        runner._cancel_selection = Mock()
        runner.appear = Mock(return_value=True)
        return runner

    def test_no_candidate_fails_without_submitting(self):
        runner = self._runner()
        runner.find_candidates = Mock(return_value=[])
        with self.assertRaises(RequestHumanTakeover):
            runner.maintain(now=datetime(2026, 9, 10, 12))
        self.assertFalse(any(call.args and getattr(call.args[0], 'name', '') ==
                             'DORM_SELECTION_CONFIRM' for call in runner.device.click.call_args_list))
        runner._cancel_selection.assert_called_once()

    def test_preflight_failure_cancels_selection_without_submitting(self):
        candidate = submarine()
        runner = self._runner()
        runner.find_candidates = Mock(return_value=[candidate])
        runner._draft = Mock(side_effect=RequestHumanTakeover('mock preflight failure'))
        with self.assertRaises(RequestHumanTakeover):
            runner.maintain(now=datetime(2026, 9, 10, 12))
        runner._draft.assert_called_once()
        self.assertEqual(runner._cancel_selection.call_count, 2)
        self.assertFalse(any(call.args and getattr(call.args[0], 'name', '') ==
                             'DORM_SELECTION_CONFIRM' for call in runner.device.click.call_args_list))

    def test_daily_gate_skips_today_and_runs_after_previous_day(self):
        config = SimpleNamespace(
            DormTraining_Enable=True,
            DormTraining_LastCheck=datetime.now().replace(microsecond=0),
        )
        with patch('module.dorm.training.DormTraining') as task:
            maintain_dorm_if_due(config, object())
            task.assert_not_called()
            config.DormTraining_LastCheck = datetime.now() - timedelta(days=1)
            maintain_dorm_if_due(config, object())
        task.assert_called_once()

    def test_incomplete_card_star_copy_is_rejected_before_click(self):
        import numpy as np
        from module.os.training_ui import CATALOG

        name = next(name for name, data in CATALOG.items() if data['max_stars'] > 2)
        ship = ShipCandidate(name, '白鹰', 'submarine', 90, False, True, None, None)
        card = SimpleNamespace(area=(100, 100, 200, 200))
        runner = DormTraining.__new__(DormTraining)
        runner.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), click=Mock())
        runner._scan_selection = Mock(return_value=card)
        runner._wait = Mock()
        incomplete = np.array([
            [0, 0, 0, 0, 0],
            [1, 1, 10, 10, 70],
            [20, 1, 10, 10, 70],
        ])
        with patch('module.dorm.training.DORM_SCROLL.set_top'), \
                patch('module.dorm.training.OCR_DOCK_SELECTED.ocr', return_value=(1, 0, 2)), \
                patch('module.dorm.training.cv2.connectedComponentsWithStats',
                      return_value=(None, None, incomplete, None)):
            with self.assertRaises(RequestHumanTakeover):
                runner._toggle(ship, 1, 2)
        runner.device.click.assert_not_called()


class TrainingInventoryMockTest(unittest.TestCase):
    def test_long_inventory_scan_clears_verified_scroll_progress(self):
        import numpy as np

        class FakeDevice:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
                self.click_record = deque(maxlen=15)
                self.clear_count = 0
                self.max_recorded = 0

            def screenshot(self):
                return None

            def sleep(self, _seconds):
                return None

            def swipe(self, _p1, _p2, name='SWIPE', **_kwargs):
                self.click_record.append(str(name))
                self.max_recorded = max(self.max_recorded, len(self.click_record))
                if Counter(self.click_record).most_common(1)[0][1] >= 12:
                    raise GameTooManyClickError('too many scrolls')

            def click_record_clear(self):
                self.clear_count += 1
                self.click_record.clear()

        class FakeScroll:
            def __init__(self, device):
                self.device = device
                self.page = 0

            def set_top(self, main):
                self.page = 0

            def at_bottom(self, main):
                return self.page >= 20

            def cal_position(self, main):
                return self.page / 20

            def next_page(self, main, page=0.45):
                self.device.swipe(None, None, name='TrainingInventoryScroll')
                self.page += 1

        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = FakeDevice()
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)
        scroll = FakeScroll(inventory.device)

        def find_book(_image, key):
            return (400, 300) if scroll.page >= 13 else None

        with patch('module.storage.training_inventory.INVENTORY_SCROLL', scroll), \
                patch('module.storage.training_inventory.item_position', side_effect=find_book), \
                patch.object(inventory, '_read_item', return_value=1957):
            self.assertEqual(inventory.read_counts(['exp_book_t1']), {'exp_book_t1': 1957})

        self.assertEqual(scroll.page, 13)
        self.assertEqual(inventory.device.clear_count, 13)
        self.assertLess(inventory.device.max_recorded, 12)

    def test_inventory_scan_rejects_unverified_page_progress(self):
        import numpy as np

        class FakeDevice:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
                self.click_record_clear = Mock()

            def screenshot(self):
                return None

            def sleep(self, _seconds):
                return None

            def swipe(self, _p1, _p2, name='SWIPE', **_kwargs):
                return None

        class StuckScroll:
            def set_top(self, main):
                return None

            def at_bottom(self, main):
                return False

            def cal_position(self, main):
                return 0.2

            def next_page(self, main, page=0.45):
                main.device.swipe(None, None, name='TrainingInventoryScroll')

        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = FakeDevice()
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)
        with patch('module.storage.training_inventory.INVENTORY_SCROLL', StuckScroll()), \
                patch('module.storage.training_inventory.item_position', return_value=None):
            with self.assertRaises(RequestHumanTakeover):
                inventory.read_counts(['exp_book_t1'])
        inventory.device.click_record_clear.assert_not_called()

    def test_missing_item_at_verified_bottom_never_becomes_zero(self):
        import numpy as np
        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                           screenshot=Mock(), sleep=Mock())
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)
        with patch('module.storage.training_inventory.item_position', return_value=None), \
                patch('module.storage.training_inventory.INVENTORY_SCROLL.set_top'), \
                patch('module.storage.training_inventory.INVENTORY_SCROLL.at_bottom', return_value=True):
            with self.assertRaises(RequestHumanTakeover):
                inventory.read_counts(['destroyer'])

    def test_stalled_scroll_at_the_list_end_completes_the_scan(self):
        import numpy as np

        class FakeDevice:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)

            def screenshot(self):
                return None

            def sleep(self, _seconds):
                return None

            def click_record_clear(self):
                return None

        class StalledScroll:
            """The real CN material page: the thumb stops at 0.893 of the track.

            Scroll.set() only reports a stall once it has given up, i.e. with the
            thumb already sitting at the last reachable position.
            """

            END = 0.893

            def __init__(self):
                self.position = 0.0
                self.stalled = False

            def set_top(self, main):
                self.position = 0.0
                self.stalled = False

            def at_bottom(self, main):
                return False

            def cal_position(self, main):
                return self.position

            def next_page(self, main, page=0.45):
                # 541 px of calibrated track, 414.5 px of thumb travel: the last
                # reachable position is 0.893 and set() gives up there.
                self.position = min(self.position + 0.075, self.END)
                self.stalled = self.position >= self.END

        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = FakeDevice()
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)
        scroll = StalledScroll()

        def find_book(_image, key):
            return (400, 300) if scroll.position >= scroll.END else None

        with patch('module.storage.training_inventory.INVENTORY_SCROLL', scroll), \
                patch('module.storage.training_inventory.item_position', side_effect=find_book), \
                patch.object(inventory, '_read_item', return_value=1957):
            self.assertEqual(inventory.read_counts(['exp_book_t1']), {'exp_book_t1': 1957})

        self.assertTrue(scroll.stalled)

    def test_the_real_scroll_stall_completes_the_scan(self):
        """End to end through Scroll.set(), not a stubbed ``stalled`` flag.

        The calibration is the production one, 541 px of track, while the thumb
        only travels 414.5 px (38.0 -> 452.5, measured on the incident): the last
        reachable position is 0.893, ``at_bottom()`` needs > 0.95 and
        ``next_page(0.45)`` targets 0.969, so the scan used to give up with
        ``Inventory scan stopped before verified bottom``.
        """
        import numpy as np
        from module.ui.scroll import Scroll
        from tests.test_training_dock_scan import Main, ProbeDevice, ProbeTimer

        class PageScroll(Scroll):
            """INVENTORY_SCROLL whose reported position is driven by the device."""

            def __init__(self):
                super().__init__((1257, 94, 1264, 635), (247, 211, 66),
                                 name='TrainingInventoryScroll')
                self.length = 78
                self.position = 0.0

            def ready(self):
                self.drag_interval = ProbeTimer()
                self.drag_timeout = collections.namedtuple('_Timer', 'reset reached')(
                    lambda: None, lambda: False)
                return self

            def cal_position(self, main):
                return self.position

        class FakeDevice:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
                self.clear_count = 0

            def screenshot(self):
                return None

            def sleep(self, _seconds):
                return None

            def swipe(self, p1, p2, duration=(0.1, 0.2), name='SWIPE', distance_check=True):
                if np.linalg.norm(np.subtract(p1, p2)) < 10:
                    return
                direction = 1 if p2[1] > p1[1] else -1
                # The page turn the incident log measured: the thumb moved
                # 452.5 - 389.5 = 63 px of a 415 px travel, 0.075 of the track.
                self.scroll.position = min(max(self.scroll.position + direction * 0.075, 0.0),
                                           self.scroll.END)

            def click_record_clear(self):
                self.clear_count += 1

        scroll = PageScroll()
        scroll.END = 0.893
        device = FakeDevice()
        device.scroll = scroll
        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = device
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)

        def find_book(_image, key):
            # Only visible on the last screenful, i.e. after the scroll stalled.
            return (400, 300) if scroll.stalled else None

        with patch('module.storage.training_inventory.INVENTORY_SCROLL', scroll.ready()), \
                patch('module.storage.training_inventory.item_position', side_effect=find_book), \
                patch.object(inventory, '_read_item', return_value=1957):
            self.assertEqual(inventory.read_counts(['exp_book_t1']), {'exp_book_t1': 1957})

        self.assertTrue(scroll.stalled)
        self.assertAlmostEqual(scroll.position, scroll.END)

    def test_scroll_stalled_in_the_middle_of_the_list_still_aborts(self):
        import numpy as np

        class FakeDevice:
            def __init__(self):
                self.image = np.zeros((720, 1280, 3), dtype=np.uint8)

            def screenshot(self):
                return None

            def sleep(self, _seconds):
                return None

            def click_record_clear(self):
                return None

        class StalledScroll:
            def __init__(self):
                self.stalled = False

            def set_top(self, main):
                self.stalled = False

            def at_bottom(self, main):
                return False

            def cal_position(self, main):
                return 0.2

            def next_page(self, main, page=0.45):
                self.stalled = True

        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.config = SimpleNamespace(SERVER='cn')
        inventory.device = FakeDevice()
        inventory.ui_goto_storage = Mock()
        inventory._storage_enter_material = Mock()
        inventory._wait_until_storage_stable = Mock()
        inventory._storage_in_material = Mock(return_value=True)
        with patch('module.storage.training_inventory.INVENTORY_SCROLL', StalledScroll()), \
                patch('module.storage.training_inventory.item_position', return_value=None):
            with self.assertRaises(RequestHumanTakeover) as caught:
                inventory.read_counts(['exp_book_t1'])
        self.assertIn('stalled', str(caught.exception))

    def test_item_templates_and_count_limits_are_type_specific(self):
        self.assertEqual(ITEM_NAMES['destroyer'], '驱逐改造图纸T3')
        self.assertEqual(ITEM_NAMES['cruiser'], '巡洋改造图纸T3')
        self.assertEqual(ITEM_NAMES['battleship'], '战列改造图纸T3')
        self.assertEqual(ITEM_NAMES['carrier'], '航母改造图纸T3')
        self.assertEqual(ITEM_NAMES['exp_book_t1'], '舰艇演习数据T1')
        self.assertEqual(parse_owned_count('47', 'destroyer'), 47)
        self.assertEqual(parse_owned_count('1957', 'exp_book_t1'), 1957)
        self.assertIsNone(parse_owned_count('3001', 'exp_book_t1'))
        self.assertIsNone(parse_owned_count('x', 'destroyer'))

    def test_detail_ocr_requires_exact_title_and_stable_count(self):
        inventory = TrainingInventory.__new__(TrainingInventory)
        inventory.device = SimpleNamespace(image=object(), click=Mock(), screenshot=Mock())
        inventory._storage_in_material = Mock(return_value=True)
        inventory._wait = Mock()
        inventory._info_visible = Mock(return_value=True)

        ocr_values = iter(('驱逐改造图纸T3', '47', '驱逐改造图纸T3', '47'))

        def ocr_factory(*args, **kwargs):
            return SimpleNamespace(ocr=lambda image: next(ocr_values))

        with patch('module.storage.training_inventory.Ocr', side_effect=ocr_factory):
            self.assertEqual(inventory._read_item('destroyer', (100, 100)), 47)
        inventory.device.click.assert_called()

    def test_checked_in_storage_fixtures_distinguish_t3_and_t2(self):
        import cv2
        fixtures = Path(__file__).parent / 'fixtures' / 'training_inventory'
        page3 = cv2.imread(str(fixtures / 'storage-page3.png'), cv2.IMREAD_COLOR)
        page6 = cv2.imread(str(fixtures / 'storage-page6.png'), cv2.IMREAD_COLOR)
        page7 = cv2.imread(str(fixtures / 'storage-page7.png'), cv2.IMREAD_COLOR)
        self.assertIsNotNone(page3)
        self.assertIsNotNone(page6)
        self.assertIsNotNone(page7)
        page3 = cv2.cvtColor(page3, cv2.COLOR_BGR2RGB)
        page6 = cv2.cvtColor(page6, cv2.COLOR_BGR2RGB)
        page7 = cv2.cvtColor(page7, cv2.COLOR_BGR2RGB)
        for key in ('destroyer', 'cruiser', 'battleship', 'carrier'):
            with self.subTest(key=key):
                self.assertIsNotNone(item_position(page3, key))
        self.assertIsNotNone(item_position(page7, 'exp_book_t1'))
        self.assertIsNone(item_position(page6, 'exp_book_t1'))


if __name__ == '__main__':
    unittest.main()
