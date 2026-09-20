import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.combat.assets import BATTLE_STATUS_S
from module.combat import battle_result
from module.combat.battle_result import (battle_result_click_timer, handle_battle_result_screen,
                                         match_battle_result_button)

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / 'tests/fixtures/battle_result'

# Clickable area of the battle result screen, shared by BATTLE_STATUS_* and GET_ITEMS_*.
SKIP_AREA = (1000, 631, 1055, 689)


def clear():
    battle_result.battle_result_click_timer.reset()
    battle_result.battle_result_click_timer._start = 0
    battle_result.battle_result_attempt = 0
    battle_result.battle_result_clicked_at = 0.


@contextmanager
def fresh_click_state():
    """Reset the module level click state of the handler, and restore it after."""
    clear()
    try:
        yield
    finally:
        clear()


class BattleResultFrameTest(unittest.TestCase):
    """The battle result screen that blocked GemsFarming on 2026-09-20.

    Live 15:48:25 and 15:51:12, both CRITICAL `Game page unknown`: the scheduler had been
    restarted while a battle of event a3 was running, so the display kept the result screen.
    The archived frames are the error dumps log/error/1789890505865 and 1789890672420.
    Nothing in UI.ui_get_current_page() skips a result screen, so the ten second page poll
    ended in GamePageUnknownError.
    """

    def image(self, name):
        return np.asarray(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))

    def app(self, name, click, in_combat=False):
        return SimpleNamespace(
            device=SimpleNamespace(image=self.image(name), click=click),
            is_combat_executing=lambda: in_combat,
        )

    def assert_in_area(self, point, area):
        x, y = point
        self.assertTrue(area[0] <= x <= area[2], f'x of {point} is outside {area}')
        self.assertTrue(area[1] <= y <= area[3], f'y of {point} is outside {area}')

    def test_rank_button_of_the_result_screen_is_localized(self):
        for name in ('result-s-1551', 'result-s-1548', 'result-s-final'):
            with self.subTest(name=name):
                button = match_battle_result_button(self.image(name))
                self.assertIs(button, BATTLE_STATUS_S)
                # Recognition signal is the rank icon, localization is the clickable area of
                # the result screen, not the matching area of the icon.
                self.assertEqual(tuple(button.area), (643, 297, 722, 317))
                self.assertEqual(tuple(button.button), SKIP_AREA)

    def test_result_screen_is_not_detected_on_the_map(self):
        # Frame of the same stage after the result screen was clicked away.
        self.assertIsNone(match_battle_result_button(self.image('map-after-continue')))

    def test_result_screen_is_skipped_when_the_page_is_unknown(self):
        clicked = []
        app = self.app('result-s-1551', lambda point: clicked.append(point))
        with fresh_click_state():
            self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(clicked), 1)
            self.assert_in_area(clicked[0], SKIP_AREA)
            # The click timer prevents a burst of clicks while the screen switches.
            self.assertFalse(handle_battle_result_screen(app))
            self.assertEqual(len(clicked), 1)

    def test_a_still_blocked_screen_is_retried_and_then_left_alone(self):
        clicked = []
        app = self.app('result-s-1551', lambda point: clicked.append(point))
        with fresh_click_state():
            for _ in range(battle_result.BATTLE_RESULT_MAX_ATTEMPT):
                battle_result_click_timer.reset()
                battle_result_click_timer._start = 0
                self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(clicked), battle_result.BATTLE_RESULT_MAX_ATTEMPT)
            for point in clicked:
                self.assert_in_area(point, SKIP_AREA)
            # After the attempts are spent the page poll reports the page instead of clicking on.
            battle_result_click_timer.reset()
            battle_result_click_timer._start = 0
            self.assertFalse(handle_battle_result_screen(app))
            self.assertEqual(len(clicked), battle_result.BATTLE_RESULT_MAX_ATTEMPT)

    def test_a_new_battle_gets_its_own_attempts(self):
        clicked = []
        app = self.app('result-s-1551', lambda point: clicked.append(point))
        with fresh_click_state():
            battle_result.battle_result_attempt = battle_result.BATTLE_RESULT_MAX_ATTEMPT
            # No click for longer than the stale timeout: this result screen is a new battle.
            battle_result.battle_result_clicked_at = 0.
            self.assertTrue(handle_battle_result_screen(app))
            self.assertEqual(len(clicked), 1)

    def test_a_running_combat_is_never_clicked(self):
        clicked = Mock()
        app = self.app('result-s-1551', clicked, in_combat=True)
        with fresh_click_state():
            self.assertFalse(handle_battle_result_screen(app))
        clicked.assert_not_called()

    def test_no_result_screen_means_no_click(self):
        clicked = Mock()
        app = self.app('map-after-continue', clicked)
        with fresh_click_state():
            self.assertFalse(handle_battle_result_screen(app))
        clicked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
