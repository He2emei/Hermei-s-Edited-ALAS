from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.coalition.assets import ACADEMY_EASY, ACADEMY_MODE_STORY
from module.coalition.truth_academy import TruthAcademyReader
from module.coalition.combat import CoalitionCombat


class TestTruthAcademyReader(unittest.TestCase):
    @staticmethod
    def put_template(image, button):
        button.ensure_template()
        x1, y1, x2, y2 = button.area
        image[y1:y2, x1:x2] = button.image

    def test_main_page_composite_matches(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        from module.coalition.truth_academy import (
            TRUTH_MAIN_CHECK, TRUTH_HOME, TRUTH_EASY,
            TRUTH_BATTLE_STORY_SELECTOR, TRUTH_PT_ENTRY,
        )
        for button in (TRUTH_MAIN_CHECK, TRUTH_HOME, TRUTH_EASY,
                       TRUTH_BATTLE_STORY_SELECTOR, TRUTH_PT_ENTRY):
            self.put_template(frame, button)
        self.assertEqual(TruthAcademyReader().read(frame), 'main')

    def test_simple_prep_composite_matches(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        from module.coalition.truth_academy import (
            TRUTH_PREP_CHECK, TRUTH_CLOSE, TRUTH_PROCEED, TRUTH_RECOMMEND,
        )
        for button in (TRUTH_PREP_CHECK, TRUTH_CLOSE,
                       TRUTH_PROCEED, TRUTH_RECOMMEND):
            self.put_template(frame, button)
        reader = TruthAcademyReader()
        self.assertEqual(reader.read(frame), 'simple_preparation')
        self.assertEqual(reader.read_reward(frame), 'unknown')

    def test_known_legacy_academy_controls_are_not_truth_academy(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.put_template(frame, ACADEMY_EASY)
        self.put_template(frame, ACADEMY_MODE_STORY)
        self.assertEqual(TruthAcademyReader().read(frame), 'unknown')

    def test_incomplete_and_wrong_size_images_are_rejected(self):
        reader = TruthAcademyReader()
        self.assertEqual(reader.read(np.zeros((720, 1280, 3), dtype=np.uint8)), 'unknown')
        self.assertEqual(reader.read(np.zeros((720, 1280, 4), dtype=np.uint8)), 'unknown')
        self.assertEqual(reader.read(np.zeros((720, 1280), dtype=np.uint8)), 'unknown')
        self.assertEqual(reader.read(None), 'unknown')

    def test_battle_result_and_total_rewards_require_matching_title_and_button(self):
        from module.coalition.truth_academy import (
            TRUTH_BATTLE_RESULT_TITLE, TRUTH_BATTLE_RESULT_CONFIRM,
            TRUTH_TOTAL_REWARDS_TITLE, TRUTH_TOTAL_REWARDS_LEAVE,
        )
        reader = TruthAcademyReader()
        battle = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.put_template(battle, TRUTH_BATTLE_RESULT_TITLE)
        self.put_template(battle, TRUTH_BATTLE_RESULT_CONFIRM)
        self.assertEqual(reader.read_reward(battle), 'battle_result')

        total = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.put_template(total, TRUTH_TOTAL_REWARDS_TITLE)
        self.put_template(total, TRUTH_TOTAL_REWARDS_LEAVE)
        self.assertEqual(reader.read_reward(total), 'total_rewards')

        mismatch = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.put_template(mismatch, TRUTH_BATTLE_RESULT_TITLE)
        self.put_template(mismatch, TRUTH_TOTAL_REWARDS_LEAVE)
        self.assertEqual(reader.read_reward(mismatch), 'unknown')
        self.assertEqual(reader.read_reward(np.zeros((720, 1280, 3), dtype=np.uint8)), 'unknown')

    @staticmethod
    def fake_combat(server='cn', event='coalition_20261124'):
        device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), screenshots=0)
        def screenshot():
            device.screenshots += 1
        device.screenshot = screenshot
        return SimpleNamespace(
            config=SimpleNamespace(SERVER=server, Campaign_Event=event),
            device=device,
            appear_then_click=Mock(return_value=True),
        )

    def test_settlement_handler_is_disabled_for_wrong_server_or_event(self):
        for server, event in (('en', 'coalition_20261124'), ('cn', 'coalition_20260723')):
            combat = self.fake_combat(server, event)
            with patch('module.coalition.combat.TruthAcademyReader') as reader:
                self.assertFalse(CoalitionCombat.handle_truth_academy_reward(combat))
                reader.assert_not_called()
            combat.appear_then_click.assert_not_called()
            self.assertEqual(combat.device.screenshots, 0)

    def test_unknown_settlement_candidate_does_not_click(self):
        combat = self.fake_combat()
        with patch('module.coalition.combat.TruthAcademyReader') as reader:
            reader.return_value.read_reward.return_value = 'unknown'
            self.assertFalse(CoalitionCombat.handle_truth_academy_reward(combat))
        combat.appear_then_click.assert_not_called()
        self.assertEqual(combat.device.screenshots, 0)

    def test_changed_second_settlement_frame_does_not_click(self):
        combat = self.fake_combat()
        with patch('module.coalition.combat.TruthAcademyReader') as reader:
            reader.return_value.read_reward.side_effect = ['battle_result', 'total_rewards']
            self.assertTrue(CoalitionCombat.handle_truth_academy_reward(combat))
        combat.appear_then_click.assert_not_called()
        self.assertEqual(combat.device.screenshots, 1)

    def test_stable_result_states_request_one_native_two_second_click(self):
        from module.coalition.truth_academy import (
            TRUTH_BATTLE_RESULT_CONFIRM, TRUTH_TOTAL_REWARDS_LEAVE,
        )
        for state, expected_button in (
            ('battle_result', TRUTH_BATTLE_RESULT_CONFIRM),
            ('total_rewards', TRUTH_TOTAL_REWARDS_LEAVE),
        ):
            combat = self.fake_combat()
            with patch('module.coalition.combat.TruthAcademyReader') as reader:
                reader.return_value.read_reward.side_effect = [state, state]
                self.assertTrue(CoalitionCombat.handle_truth_academy_reward(combat))
            self.assertEqual(combat.device.screenshots, 1)
            combat.appear_then_click.assert_called_once_with(
                expected_button, offset=(0, 0), interval=2)

    def test_legacy_academy_and_preparation_frames_are_reward_negatives(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.put_template(frame, ACADEMY_EASY)
        self.put_template(frame, ACADEMY_MODE_STORY)
        self.assertEqual(TruthAcademyReader().read_reward(frame), 'unknown')


if __name__ == '__main__':
    unittest.main()
