import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from module.minigame.minigame import Minigame, MinigameRun, is_minigame_home, is_minigame_list
from module.minigame.new_year_challenge import NewYearChallenge
from module.minigame.assets import BACK, GOTO_CHOOSE_GAME, NEW_YEAR_CHALLENGE_END
from module.ui.assets import GAME_ROOM_CHECK
from unittest.mock import patch


FIXTURES = Path(__file__).parent / 'fixtures'


class ReplayDevice:
    def __init__(self, images, transition_button=None):
        self.images = images
        self.image = images[0]
        self.clicks = []
        self.transition_button = transition_button
        self.screenshots = 0

    def stuck_record_add(self, _button):
        pass

    def click(self, button):
        self.clicks.append(button)
        if len(self.images) > 1 and self.image is self.images[0] \
                and button is self.transition_button:
            self.image = self.images[1]

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > 12:
            raise AssertionError('minigame entry repeated clicks instead of reaching the list')


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

        with patch('module.minigame.new_year_challenge.MINIGAME_SCROLL.set', return_value=True) as set_scroll:
            with self.assertRaises(StopReplay):
                runner.choose_game()

        set_scroll.assert_called_once()
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


class StopReplay(Exception):
    pass
