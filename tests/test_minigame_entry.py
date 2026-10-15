import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from module.minigame.minigame import Minigame, MinigameRun, is_minigame_home, is_minigame_list
from module.minigame.new_year_challenge import NewYearChallenge
from module.exception import RequestHumanTakeover
from module.minigame.assets import (BACK, GOTO_CHOOSE_GAME, NEW_YEAR_CHALLENGE_END,
                                    NEW_YEAR_CHALLENGE_ENTRANCE)
from module.ui.assets import GAME_ROOM_CHECK
from unittest.mock import patch


FIXTURES = Path(__file__).parent / 'fixtures'


class ReplayDevice:
    def __init__(self, images, transition_button=None, transition_swipe=None,
                 advance_on_screenshot=None):
        self.images = images
        self.image = images[0]
        self.index = 0
        self.clicks = []
        self.swipes = []
        self.transition_button = transition_button
        self.transition_swipe = transition_swipe
        self.screenshots = 0
        self.advance_on_screenshot = advance_on_screenshot
        self.sleeps = []

    def stuck_record_add(self, _button):
        pass

    def click(self, button):
        self.clicks.append(button)
        if self.index < len(self.images) - 1 and button is self.transition_button:
            self._advance()

    def swipe(self, p1, p2, **kwargs):
        self.swipes.append((p1, p2, kwargs))
        if self.index < len(self.images) - 1 and (p1, p2) == self.transition_swipe:
            self._advance()

    def _advance(self):
        self.index += 1
        self.image = self.images[self.index]

    def screenshot(self):
        self.screenshots += 1
        if self.advance_on_screenshot == self.screenshots and self.index < len(self.images) - 1:
            self._advance()
        if self.screenshots > 12:
            raise AssertionError('minigame entry repeated clicks instead of reaching the list')

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def load_fixture(name):
    return np.asarray(Image.open(FIXTURES / name).convert('RGB'))


def minigame_runner(images, transition_button=None):
    runner = MinigameRun.__new__(MinigameRun)
    runner.config = SimpleNamespace(BUTTON_OFFSET=30)
    runner.device = ReplayDevice(images, transition_button=transition_button)
    runner.interval_timer = {}
    runner.deal_popup = lambda: False
    runner.choose_game = lambda: setattr(runner, 'choose_game_called', True)
    runner.use_coin = lambda: False
    runner.exit_game = lambda: None
    runner.choose_game_called = False
    return runner


class MinigameEntryTest(unittest.TestCase):
    def test_real_game_list_frame_enters_choose_game_without_reclicking_goto(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        runner = minigame_runner([game_list])

        runner.minigame_run()

        self.assertTrue(runner.choose_game_called)
        self.assertEqual(runner.device.clicks, [])

    def test_real_home_frame_clicks_goto_once_then_enters_game_list(self):
        home = load_fixture('minigame_game_room_main_20261016.png')
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        runner = minigame_runner([home, game_list], transition_button=GOTO_CHOOSE_GAME)

        runner.minigame_run()

        self.assertTrue(runner.choose_game_called)
        self.assertEqual(len(runner.device.clicks), 1)

    def test_shared_detection_uses_real_header_and_scrollbar(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        home = load_fixture('minigame_game_room_main_20261016.png')
        list_runner = minigame_runner([game_list])
        home_runner = minigame_runner([home])

        self.assertTrue(list_runner.appear(GAME_ROOM_CHECK, offset=(5, 5)))
        self.assertTrue(is_minigame_list(list_runner))
        self.assertFalse(is_minigame_home(list_runner))
        self.assertFalse(is_minigame_list(home_runner))
        self.assertTrue(is_minigame_home(home_runner))

    def test_go_to_main_page_returns_from_confirmed_list_without_goto_click(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        home = load_fixture('minigame_game_room_main_20261016.png')
        runner = Minigame.__new__(Minigame)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([game_list, home], transition_button=BACK)
        runner.interval_timer = {}
        runner.ui_additional = lambda: False

        runner.go_to_main_page()

        self.assertIs(runner.device.image, home)
        self.assertEqual(runner.device.clicks, [BACK])

    def test_collect_coin_returns_from_confirmed_list_without_goto_click(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        home = load_fixture('minigame_game_room_main_20261016.png')
        runner = Minigame.__new__(Minigame)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([game_list, home], transition_button=BACK)
        runner.interval_timer = {}
        runner.ui_additional = lambda: False

        runner.collect_coin()

        self.assertIs(runner.device.image, home)
        self.assertNotIn(GOTO_CHOOSE_GAME, runner.device.clicks)

    def test_new_year_choose_game_scrolls_confirmed_list_without_clicking_goto(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([game_list])
        runner.interval_timer = {}
        runner.deal_popup = lambda: False
        runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.set',
                   side_effect=AssertionError('fixed target scroll must not run')):
            with self.assertRaises(StopReplay):
                runner.choose_game()

        self.assertEqual(len(runner.device.swipes), 1)
        self.assertIn(runner.device.swipes[0][:2], (((1150, 300), (1150, 450)),
                                                    ((1150, 450), (1150, 300))))
        self.assertEqual(runner.device.clicks, [])


    def test_unknown_page_does_not_click_goto_or_back(self):
        unknown = load_fixture('dorm_albacore_mu_detail_20260929.png')
        for operation in ('entry', 'return_home', 'collect_coin'):
            with self.subTest(operation=operation):
                if operation == 'entry':
                    runner = minigame_runner([unknown])
                    runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())
                    run = runner.minigame_run
                else:
                    runner = Minigame.__new__(Minigame)
                    runner.config = SimpleNamespace(BUTTON_OFFSET=30)
                    runner.device = ReplayDevice([unknown])
                    runner.interval_timer = {}
                    runner.ui_additional = lambda: False
                    runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())
                    run = runner.go_to_main_page if operation == 'return_home' else runner.collect_coin

                with self.assertRaises(StopReplay):
                    run()
                self.assertEqual(runner.device.clicks, [])

    def test_new_year_exit_stops_on_confirmed_list_without_reclicking_goto(self):
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([game_list])
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        runner.exit_game()

        self.assertEqual(runner.device.clicks, [])

    def test_new_year_end_returns_through_back_to_confirmed_list(self):
        game_screen = load_fixture('dorm_albacore_mu_detail_20260929.png')
        game_list = load_fixture('minigame_choose_entry_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([game_screen, game_list], transition_button=BACK)
        runner.interval_timer = {}
        runner.deal_popup = lambda: False
        real_appear = runner.appear
        end_seen = [False]

        def appear(button, *args, **kwargs):
            if button is NEW_YEAR_CHALLENGE_END and not end_seen[0]:
                end_seen[0] = True
                return True
            return real_appear(button, *args, **kwargs)

        runner.appear = appear
        runner.exit_game()

        self.assertEqual(runner.device.clicks, [BACK])


    def test_visible_entrance_during_click_cooldown_waits_without_scrolling(self):
        visible = load_fixture('minigame_new_year_entrance_visible_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([visible])
        runner.interval_timer = {NEW_YEAR_CHALLENGE_ENTRANCE.name: CoolingInterval()}
        runner.deal_popup = lambda: False
        runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.set') as set_scroll:
            with self.assertRaises(StopReplay):
                runner.choose_game()

        set_scroll.assert_not_called()
        self.assertEqual(runner.device.clicks, [])

    def test_one_verified_content_swipe_reveals_and_selects_new_year_card(self):
        before = load_fixture('minigame_new_year_list_before_sweep_20261016.png')
        target_visible = load_fixture('minigame_new_year_list_target_visible_20261016.png')
        selected = load_fixture('minigame_new_year_selected_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice(
            [before, target_visible, selected],
            transition_button=NEW_YEAR_CHALLENGE_ENTRANCE,
            transition_swipe=((1150, 300), (1150, 450)),
        )
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.set',
                   side_effect=AssertionError('fixed target scroll must not run')):
            runner.choose_game()

        self.assertEqual(len(runner.device.swipes), 1)
        self.assertEqual(runner.device.swipes[0][:2], ((1150, 300), (1150, 450)))
        self.assertEqual(runner.device.clicks, [NEW_YEAR_CHALLENGE_ENTRANCE])

    def test_three_stationary_content_swipes_request_takeover(self):
        before = load_fixture('minigame_new_year_list_before_sweep_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([before])
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.set',
                   side_effect=AssertionError('fixed target scroll must not run')):
            with self.assertRaisesRegex(RequestHumanTakeover, '3 consecutive content swipes'):
                runner.choose_game()

        self.assertEqual(len(runner.device.swipes), 3)

    def test_unknown_page_during_new_year_scan_waits_without_swiping(self):
        unknown = load_fixture('dorm_albacore_mu_detail_20260929.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([unknown])
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())
        with self.assertRaises(StopReplay):
            runner.choose_game()

        self.assertEqual(runner.device.swipes, [])
        self.assertEqual(runner.device.clicks, [])

    def test_home_with_goto_cooldown_waits_without_takeover_or_swipe(self):
        home = load_fixture('minigame_game_room_main_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([home])
        runner.interval_timer = {GOTO_CHOOSE_GAME.name: CoolingInterval()}
        runner.deal_popup = lambda: False
        runner.device.screenshot = lambda: (_ for _ in ()).throw(StopReplay())

        with self.assertRaises(StopReplay):
            runner.choose_game()

        self.assertEqual(runner.device.clicks, [])
        self.assertEqual(runner.device.swipes, [])

    def test_unknown_transition_after_card_click_waits_for_prepare_page(self):
        target_visible = load_fixture('minigame_new_year_list_target_visible_20261016.png')
        unknown = load_fixture('dorm_albacore_mu_detail_20260929.png')
        selected = load_fixture('minigame_new_year_selected_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([target_visible, unknown, selected],
                                     transition_button=NEW_YEAR_CHALLENGE_ENTRANCE,
                                     advance_on_screenshot=1)
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        runner.choose_game()

        self.assertEqual(runner.device.clicks, [NEW_YEAR_CHALLENGE_ENTRANCE])
        self.assertEqual(runner.device.swipes, [])

    def test_content_swipe_settles_before_next_frame_progress_check(self):
        before = load_fixture('minigame_new_year_list_before_sweep_20261016.png')
        target_visible = load_fixture('minigame_new_year_list_target_visible_20261016.png')
        selected = load_fixture('minigame_new_year_selected_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([before, target_visible, selected],
                                     transition_button=NEW_YEAR_CHALLENGE_ENTRANCE,
                                     transition_swipe=((1150, 300), (1150, 450)))
        runner.interval_timer = {}
        runner.deal_popup = lambda: False

        runner.choose_game()

        self.assertEqual(runner.device.sleeps, [1])

    def test_scan_is_bounded_to_eight_content_swipes(self):
        before = load_fixture('minigame_new_year_list_before_sweep_20261016.png')
        runner = NewYearChallenge.__new__(NewYearChallenge)
        runner.config = SimpleNamespace(BUTTON_OFFSET=30)
        runner.device = ReplayDevice([before])
        runner.interval_timer = {}
        runner.deal_popup = lambda: False
        positions = [0.51, 0.45, 0.39, 0.33, 0.27, 0.21, 0.15, 0.09, 0.03]

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.cal_position',
                   side_effect=positions):
            with self.assertRaisesRegex(RequestHumanTakeover, '8 content swipes'):
                runner.choose_game()

        self.assertEqual(len(runner.device.swipes), 8)


class StopReplay(Exception):
    pass


class CoolingInterval:
    limit = 3

    def reached(self):
        return False
