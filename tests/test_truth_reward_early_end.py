from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from module.combat.auto_search_combat import AutoSearchCombat
from module.coalition.combat import CoalitionCombat
from module.coalition.truth_academy import (
    TRUTH_TOTAL_REWARDS_LEAVE, TRUTH_TOTAL_REWARDS_TITLE, TruthAcademyReader,
)
from module.os_ash.assets import BATTLE_STATUS


class TruthRewardEarlyEndTests(unittest.TestCase):
    @staticmethod
    def put_template(frame, button):
        button.ensure_template()
        x1, y1, x2, y2 = button.area
        frame[y1:y2, x1:x2] = button.image

    def total_rewards_with_battle_hud(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for button in (TRUTH_TOTAL_REWARDS_TITLE, TRUTH_TOTAL_REWARDS_LEAVE,
                       BATTLE_STATUS):
            self.put_template(frame, button)
        return frame

    def test_same_frame_hud_triggers_old_end_but_verified_reward_wins(self):
        frame = self.total_rewards_with_battle_hud()
        self.assertEqual(TruthAcademyReader().read_reward(frame), 'total_rewards')

        # This reproduces the failure mode: the ordinary battle HUD cue is also
        # present, so the unchanged legacy end predicate would accept this frame.
        legacy = SimpleNamespace(appear=lambda button, offset: button.match(frame, offset=offset))
        self.assertTrue(CoalitionCombat.auto_search_combat_end(legacy))

        new = SimpleNamespace(
            config=SimpleNamespace(SERVER='cn', Campaign_Event='coalition_20261124'),
            device=SimpleNamespace(image=frame),
        )
        self.assertTrue(CoalitionCombat.auto_search_combat_early_end(new))

    def test_early_end_hook_fails_closed_for_other_event_or_server(self):
        frame = self.total_rewards_with_battle_hud()
        for server, event in (('en', 'coalition_20261124'),
                              ('cn', 'coalition_20251120')):
            app = SimpleNamespace(
                config=SimpleNamespace(SERVER=server, Campaign_Event=event),
                device=SimpleNamespace(image=frame),
            )
            with patch('module.coalition.combat.TruthAcademyReader') as reader:
                self.assertFalse(CoalitionCombat.auto_search_combat_early_end(app))
                reader.assert_not_called()

        unknown = np.zeros_like(frame)
        app = SimpleNamespace(
            config=SimpleNamespace(SERVER='cn', Campaign_Event='coalition_20261124'),
            device=SimpleNamespace(image=unknown),
        )
        self.assertFalse(CoalitionCombat.auto_search_combat_early_end(app))

    def test_auto_search_yields_before_loading_controls_and_restores_interval(self):
        calls = []
        app = SimpleNamespace(
            device=SimpleNamespace(
                stuck_record_clear=lambda: calls.append('stuck-clear'),
                click_record_clear=lambda: calls.append('click-clear'),
                screenshot_interval_set=lambda *args: calls.append(('interval', args)),
            ),
            loop=lambda: iter((None,)),
            auto_search_combat_early_end=lambda: calls.append('early-check') or True,
            handle_combat_automation_confirm=lambda: calls.append('combat-control') or False,
        )
        AutoSearchCombat.auto_search_combat_execute(app, emotion_reduce=True, fleet_index=1)
        self.assertEqual(calls[-2:], ['early-check', ('interval', ())])
        self.assertNotIn('combat-control', calls)
        self.assertEqual(calls[0], 'stuck-clear')
        self.assertEqual(calls[1], 'click-clear')

    def test_reenter_classifies_reward_before_loading_or_hud_checks(self):
        calls = []
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        device = SimpleNamespace(image=frame)
        def screenshot():
            calls.append('screenshot')
        device.screenshot = screenshot
        app = SimpleNamespace(device=device)
        reward_count = [0]
        def handle_reward():
            calls.append('reward')
            reward_count[0] += 1
            return reward_count[0] == 1
        app.handle_truth_academy_reward = handle_reward
        app.is_combat_loading = lambda: calls.append('loading') or True
        app.is_combat_executing = lambda: calls.append('executing') or True

        class FakeTimer:
            def __init__(self, *args, **kwargs):
                pass
            def reached(self):
                return False
            def reset(self):
                pass

        with patch('module.coalition.combat.Timer', FakeTimer):
            CoalitionCombat.coalition_combat_re_enter(app)
        self.assertLess(calls.index('reward'), calls.index('loading'))
        self.assertNotIn('executing', calls)

    def test_default_virtual_hook_is_false(self):
        self.assertFalse(AutoSearchCombat.auto_search_combat_early_end(object()))


if __name__ == '__main__':
    unittest.main()
