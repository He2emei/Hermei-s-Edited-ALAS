from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.combat.combat import Combat
from module.combat.assets import BATTLE_PREPARATION
from module.coalition.combat import CoalitionCombat
from module.coalition.truth_academy import TRUTH_CLOSE
from module.coalition.ui import CoalitionUI
from module.exception import RequestHumanTakeover, ScriptEnd
from module.ui.assets import BACK_ARROW
from module.coalition.truth_academy_emotion import (
    TOAST_ROI, TruthAcademyEmotionReader,
)


STAGE_ROOT = Path(__file__).resolve().parents[1]
TOAST_TEMPLATE = Path('./assets/cn/coalition/TRUTH_LOW_MOOD_TOAST.png')
TOAST_FIXTURES = (
    STAGE_ROOT / 'tests' / 'fixtures' / 'low_mood_toast_20261126.png',
    STAGE_ROOT / 'tests' / 'fixtures' / 'low_mood_toast_20261126_transient.png',
)
TOAST_SOURCES = (TOAST_TEMPLATE,) + TOAST_FIXTURES


class TruthAcademyLowMoodTest(unittest.TestCase):
    def compose_toast(self):
        template = cv2.imread(str(TOAST_TEMPLATE), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(template.shape, (31, 591))
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        x1, y1, x2, y2 = TOAST_ROI
        frame[y1:y2, x1:x2] = np.repeat(template[:, :, None], 3, axis=2)
        return frame

    def compose_live_fixture(self, fixture_path=None, erase_columns=None, alter_zero=False):
        crop = cv2.imread(str(fixture_path or TOAST_FIXTURES[0]), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(crop.shape, (31, 591))
        if erase_columns is not None:
            crop = crop.copy()
            crop[:, erase_columns[0]:erase_columns[1]] = 0
        if alter_zero:
            crop = crop.copy()
            # Remove the middle stroke of the displayed zero in "<=30".
            crop[10:22, 456:461] = 0
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        x1, y1, x2, y2 = TOAST_ROI
        frame[y1:y2, x1:x2] = np.repeat(crop[:, :, None], 3, axis=2)
        return frame

    def test_only_the_cropped_generic_toast_matches(self):
        reader = TruthAcademyEmotionReader(str(TOAST_TEMPLATE))
        frame = self.compose_toast()
        self.assertTrue(reader.read_low_mood_toast(frame))
        self.assertFalse(reader.read_low_mood_toast(np.zeros_like(frame)))
        changed = frame.copy()
        x1, y1, _, _ = TOAST_ROI
        changed[y1 + 4:y1 + 25, x1 + 5:x1 + 90] = 0
        self.assertFalse(reader.read_low_mood_toast(changed))
        self.assertFalse(reader.read_low_mood_toast(np.zeros((720, 1280, 4), dtype=np.uint8)))

    def test_new_live_crop_replay_and_semantic_negatives(self):
        reader = TruthAcademyEmotionReader(str(TOAST_TEMPLATE))
        for fixture_path in TOAST_SOURCES:
            with self.subTest(fixture=fixture_path.name):
                live_frame = self.compose_live_fixture(fixture_path)
                self.assertTrue(reader.read_low_mood_toast(live_frame))
                # Each fixture must retain its <=30 and unique-text semantics.
                self.assertFalse(reader.read_low_mood_toast(
                    self.compose_live_fixture(fixture_path, (397, 466))))
                self.assertFalse(reader.read_low_mood_toast(
                    self.compose_live_fixture(fixture_path, (0, 184))))
                self.assertFalse(reader.read_low_mood_toast(
                    self.compose_live_fixture(fixture_path, (424, 438))))
                self.assertFalse(reader.read_low_mood_toast(
                    self.compose_live_fixture(fixture_path, alter_zero=True)))
                self.assertFalse(reader.read_low_mood_toast(np.zeros_like(live_frame)))
                self.assertFalse(reader.read_low_mood_toast(
                    np.zeros((720, 1280, 4), dtype=np.uint8)))

    @staticmethod
    def combat(server='cn', event='coalition_20261124', fleet='single', prep=True):
        instance = CoalitionCombat.__new__(CoalitionCombat)
        instance.config = SimpleNamespace(
            SERVER=server, Campaign_Event=event, Coalition_Fleet=fleet,
            task_delay=Mock())
        instance.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                          screenshot=Mock())
        instance.appear = Mock(return_value=prep)
        instance.appear_then_click = Mock(return_value=True)
        instance.coalition_map_exit = Mock()
        return instance

    def test_legacy_method_clicks_but_confirmed_cn_single_toast_exits_and_delays(self):
        # On the exact native BATTLE_PREPARATION page, the legacy method clicks
        # despite the independently verified low-mood warning.
        legacy = SimpleNamespace(appear_then_click=Mock(return_value=True))
        self.assertTrue(Combat.handle_battle_preparation(legacy))
        legacy.appear_then_click.assert_called_once_with(
            BATTLE_PREPARATION, offset=(20, 20), interval=2)

        instance = self.combat()
        first_fixture = self.compose_live_fixture(TOAST_FIXTURES[0])
        second_fixture = self.compose_live_fixture(TOAST_FIXTURES[1])
        instance.device.image = first_fixture
        instance.device.screenshot = Mock(side_effect=lambda: setattr(
            instance.device, 'image', second_fixture.copy()))
        instance._truth_academy_emotion_reader = TruthAcademyEmotionReader(str(TOAST_TEMPLATE))
        with self.assertRaises(ScriptEnd):
            CoalitionCombat.handle_battle_preparation(instance)
        self.assertEqual(instance.appear.call_count, 2)
        instance.coalition_map_exit.assert_called_once_with('coalition_20261124')
        instance.config.task_delay.assert_called_once_with(minute=120)
        instance.appear_then_click.assert_not_called()

    def test_changed_second_frame_is_consumed_without_delay_or_battle_click(self):
        instance = self.combat()
        instance._truth_academy_emotion_reader = SimpleNamespace(
            read_low_mood_toast=Mock(side_effect=[True, False]))
        self.assertTrue(CoalitionCombat.handle_battle_preparation(instance))
        instance.config.task_delay.assert_not_called()
        instance.coalition_map_exit.assert_not_called()
        instance.appear_then_click.assert_not_called()

    def test_single_frame_toast_is_not_enough_to_delay(self):
        instance = self.combat()
        instance.appear.side_effect = [True, False]
        instance._truth_academy_emotion_reader = SimpleNamespace(
            read_low_mood_toast=Mock(return_value=True))
        self.assertTrue(CoalitionCombat.handle_battle_preparation(instance))
        instance.config.task_delay.assert_not_called()
        instance.coalition_map_exit.assert_not_called()
        instance.appear_then_click.assert_not_called()

    def test_foreign_event_or_multi_fleet_keeps_legacy_behavior(self):
        for server, event, fleet in (
                ('en', 'coalition_20261124', 'single'),
                ('cn', 'coalition_20251120', 'single'),
                ('cn', 'coalition_20261124', 'multi')):
            instance = self.combat(server, event, fleet)
            self.assertTrue(CoalitionCombat.handle_battle_preparation(instance))
            instance.config.task_delay.assert_not_called()
            instance.coalition_map_exit.assert_not_called()
            instance.appear_then_click.assert_called_once()

    @staticmethod
    def ui(reader_values, native_values=None):
        ui = CoalitionUI.__new__(CoalitionUI)
        ui.device = SimpleNamespace(image=object(), screenshot=Mock(), click=Mock(), sleep=Mock())
        ui.appear = Mock(side_effect=native_values or [False] * 20)
        return ui

    def test_exit_accepts_only_double_frame_safe_paths(self):
        # A known main page requires two reads and causes no click.
        ui = self.ui([])
        with patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.side_effect = ['main', 'main']
            self.assertTrue(CoalitionUI._truth_academy_map_exit(ui))
        ui.device.click.assert_not_called()

        # A recognized preparation page must remain the same across frames
        # before the event-specific close template is clicked.
        ui = self.ui([])
        with patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.side_effect = [
                'normal_preparation', 'normal_preparation', 'main', 'main']
            self.assertTrue(CoalitionUI._truth_academy_map_exit(ui))
        ui.device.click.assert_called_once_with(TRUTH_CLOSE)

        # Native battle preparation requires a second native confirmation before
        # BACK_ARROW. Unknown transition after the verified click is observed safely.
        ui = self.ui([], native_values=[True, True, False])
        with patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.side_effect = ['unknown', 'unknown', 'main', 'main']
            self.assertTrue(CoalitionUI._truth_academy_map_exit(ui))
        ui.device.click.assert_called_once_with(BACK_ARROW)

    def test_exit_clicks_are_spaced_and_bounded(self):
        class FakeClock:
            now = 100.0
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds

        clock = FakeClock()
        ui = self.ui([])
        click_times = []
        ui.device.sleep = clock.sleep
        ui.device.click = lambda button: click_times.append((button, clock.now))
        with patch('module.coalition.ui.time.monotonic', clock.monotonic), \
                patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.return_value = 'normal_preparation'
            with self.assertRaises(RequestHumanTakeover):
                CoalitionUI._truth_academy_map_exit(ui)
        close_times = [at for button, at in click_times if button is TRUTH_CLOSE]
        self.assertEqual(len(close_times), 3)
        self.assertGreaterEqual(close_times[1] - close_times[0], 2)
        self.assertGreaterEqual(close_times[2] - close_times[1], 2)

    def test_unknown_transition_is_ignored_only_briefly_after_our_click(self):
        class FakeClock:
            now = 200.0
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds

        clock = FakeClock()
        ui = self.ui([])
        ui.device.sleep = clock.sleep
        ui.appear.return_value = False
        with patch('module.coalition.ui.time.monotonic', clock.monotonic), \
                patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.return_value = 'unknown'
            with self.assertRaises(RequestHumanTakeover):
                CoalitionUI._truth_academy_map_exit(ui)
        # Initial unknown has no post-click grace period or UI action.
        self.assertEqual(clock.now, 200.0)
        ui.device.click.assert_not_called()

        # Once our own verified click has left the UI unknown for more than
        # three seconds, stop without attempting another action.
        clock = FakeClock()
        clock.now = 300.0
        ui = self.ui([])
        ui.device.sleep = clock.sleep
        click_times = []
        ui.device.click = lambda button: click_times.append((button, clock.now))
        appear_calls = [0]
        def native_match(*args, **kwargs):
            appear_calls[0] += 1
            return appear_calls[0] <= 2
        ui.appear = Mock(side_effect=native_match)
        with patch('module.coalition.ui.time.monotonic', clock.monotonic), \
                patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.return_value = 'unknown'
            with self.assertRaises(RequestHumanTakeover):
                CoalitionUI._truth_academy_map_exit(ui)
        self.assertEqual([button for button, _ in click_times], [BACK_ARROW])
        self.assertGreater(clock.now, 303.0)

    def test_exit_unknown_or_single_frame_match_never_clicks(self):
        ui = self.ui([])
        with patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.return_value = 'unknown'
            with self.assertRaises(RequestHumanTakeover):
                CoalitionUI._truth_academy_map_exit(ui)
        ui.device.click.assert_not_called()

        # The first BATTLE_PREPARATION match disappears on the confirming frame.
        ui = self.ui([], native_values=[True, False, False])
        with patch('module.coalition.ui.TruthAcademyReader') as reader:
            reader.return_value.read.return_value = 'unknown'
            with self.assertRaises(RequestHumanTakeover):
                CoalitionUI._truth_academy_map_exit(ui)
        ui.device.click.assert_not_called()

    def test_new_event_exit_dispatch_does_not_replace_legacy_route(self):
        ui = CoalitionUI.__new__(CoalitionUI)
        ui.config = SimpleNamespace(SERVER='cn')
        ui._truth_academy_map_exit = Mock(return_value=True)
        CoalitionUI.coalition_map_exit(ui, 'coalition_20261124')
        ui._truth_academy_map_exit.assert_called_once_with()


    def test_interval_wait_requires_fresh_page_confirmation_before_reclick(self):
        class FakeClock:
            now = 100.0
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock = FakeClock()
        ui = self.ui([])
        ui.device.sleep = clock.sleep
        clicked = []
        ui.device.click = lambda button: clicked.append((button, clock.now))
        with patch('module.coalition.ui.time.monotonic', clock.monotonic), \
                patch('module.coalition.ui.TruthAcademyReader') as reader:
            # First close succeeds during the interval wait. The old candidate
            # would click the stale close coordinates after its two-second sleep.
            reader.return_value.read.side_effect = lambda image: (
                'normal_preparation' if clock.now < 100.1 else 'main')
            self.assertTrue(CoalitionUI._truth_academy_map_exit(ui))
        self.assertEqual(clicked, [(TRUTH_CLOSE, 100.0)])


if __name__ == '__main__':
    unittest.main()
