import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.tactical import tactical_class as tactical


class TacticalPriorityTest(unittest.TestCase):
    @staticmethod
    def make_runner():
        settings = {}
        for group, options in {
            'sort': ('rarity', 'level', 'total'),
            'index': ('all', 'main', 'vanguard'),
            'faction': ('all', 'royal', 'sakura', 'meta'),
            'rarity': ('all', 'ultra'),
            'extra': ('no_limit', 'has_skin'),
        }.items():
            settings.update({(group, name): object() for name in options})
        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(
            PriorityTraining_Ships='虎 > 安土',
            PriorityTraining_Allow125Awakening=True,
            AddNewStudent_Favorite=True,
            AddNewStudent_MinLevel=90,
            AddNewStudent_Enable=True,
        )
        # Mirrors Setting: settings maps (group, option) to buttons, while
        # settings_default records the reset baseline.
        runner.dock_filter = SimpleNamespace(
            settings=settings,
            settings_default={'sort': 'level', 'index': 'all', 'faction': 'all',
                              'rarity': 'all', 'extra': 'no_limit'},
        )
        runner.dock_favourite_set = Mock()
        runner.dock_sort_method_dsc_set = Mock()
        runner.dock_filter_set = Mock()
        runner.interval_clear = Mock()
        runner.device = SimpleNamespace(image=object(), click=Mock(), sleep=Mock(), screenshot=Mock())
        return runner

    def test_receive_redirects_completed_course_only_once_at_book_page(self):
        runner = self.make_runner()
        runner.config.AddNewStudent_Enable = True
        runner.interval_reset = Mock()
        runner.interval_clear = Mock()
        runner.interval_timer = {}
        runner.handle_rapid_training = lambda: False
        runner._tactical_get_finish = lambda: []
        runner.handle_popup_confirm = lambda *args, **kwargs: False
        runner.handle_urgent_commission = lambda: False
        runner.ui_page_main_popups = lambda: False
        runner.handle_game_tips = lambda: False
        runner.ui_main_appear_then_click = lambda *args, **kwargs: False
        books = iter(('idle_page', 'done'))
        runner._tactical_books_choose = Mock(side_effect=lambda: state.update(page=next(books)) or True)
        timer = SimpleNamespace(reached=lambda: True, reset=Mock())
        timer.start = lambda: timer
        state = {'page': 'finished_list'}

        def page_appears(page, *args, **kwargs):
            return page is tactical.page_tactical and state['page'] in ('finished_list', 'idle_page')

        def appear(button, *args, **kwargs):
            if button is tactical.TACTICAL_CLASS_START:
                return state['page'] in ('class_start', 'book_start')
            if button is tactical.REWARD_CHECK:
                return state['page'] == 'done'
            if button is tactical.DOCK_CHECK:
                return state['page'] == 'dock'
            if button is tactical.SKILL_CONFIRM:
                return state['page'] == 'skill'
            return False

        runner.appear = appear
        runner.ui_page_appear = page_appears
        runner.dock_selected = lambda: False

        def appear_then_click(button, *args, **kwargs):
            if button is tactical.ADD_NEW_STUDENT and state['page'] == 'idle_page':
                state['page'] = 'dock'
                return True
            return False

        runner.appear_then_click = appear_then_click
        selections = iter(('虎', None))

        def select_ship():
            runner.tactical_priority_current = next(selections)
            state['page'] = 'skill'
            return True

        runner.select_suitable_ship = select_ship
        runner._tactical_skill_choose = lambda: state.update(page='book_start') or True
        runner.tactical_priority_names = ('虎',)
        runner.tactical_priority_started = set()
        runner.tactical_priority_exhausted = set()
        runner.device.click = Mock()

        def click(button):
            if button is tactical.BACK_ARROW and state['page'] == 'finished_list':
                state['page'] = 'class_start'
            elif button is tactical.TACTICAL_CLASS_CANCEL:
                state['page'] = 'idle_page'

        runner.device.click.side_effect = click
        with patch.object(tactical, 'Timer', return_value=timer):
            runner.tactical_class_receive()

        self.assertEqual([call[0][0] for call in runner.device.click.call_args_list],
                         [tactical.BACK_ARROW, tactical.TACTICAL_CLASS_CANCEL])
        self.assertEqual(runner.tactical_priority_started, {'虎'})
        self.assertIsNone(runner.tactical_priority_current)
        self.assertFalse(runner.tactical_priority_boundary_redirected)
        self.assertEqual(runner.tactical_normal_filter_settings,
                         runner.dock_filter.settings_default)
        self.assertEqual(runner.tactical_normal_factions, ['royal', 'sakura'])
        runner._tactical_books_choose.assert_called_with()
        self.assertEqual(runner._tactical_books_choose.call_count, 2)

    def test_redirect_skips_newly_selected_student_and_no_config(self):
        runner = self.make_runner()
        runner.tactical_priority_names = ('虎',)
        runner.tactical_new_student_selected = True
        runner.tactical_priority_boundary_redirected = False
        self.assertFalse(runner._tactical_redirect_completed_course())
        runner.tactical_new_student_selected = False
        self.assertTrue(runner._tactical_redirect_completed_course())
        self.assertFalse(runner._tactical_redirect_completed_course())
        runner.tactical_priority_names = ()
        runner.tactical_priority_boundary_redirected = False
        self.assertFalse(runner._tactical_redirect_completed_course())

    def test_low_level_locked_priority_beats_minlevel_and_skips_unlocked_duplicate(self):
        runner = self.make_runner()
        runner.tactical_priority_names = ('虎', '安土')
        runner.tactical_priority_exhausted = set()
        runner.tactical_priority_started = set()
        runner.tactical_normal_factions = ['royal', 'sakura']
        runner.tactical_normal_filter_settings = runner.dock_filter.settings_default.copy()
        runner.appear = lambda *args, **kwargs: False
        runner.dock_selected = lambda: True
        runner.dock_select_confirm = Mock()
        runner.interval_clear = Mock()
        runner.dock_filter_set.side_effect = lambda **kwargs: setattr(
            runner, 'current_target', '虎' if kwargs['faction'] == 'royal' else '安土')

        class Card:
            area = (10, 10, 148, 214)

            def crop(self, *args, **kwargs):
                return object()

        card = Card()
        lock = iter([False, True, True])
        with patch.dict(tactical.CATALOG, {
            '虎': {'rarity': 6, 'type': 3, 'faction': 2},
            '安土': {'rarity': 6, 'type': 6, 'faction': 3},
        }, clear=False), \
                patch.object(tactical, 'dock_cards', return_value=[card]), \
                patch.object(tactical, 'dock_card_lock', side_effect=lambda *args: next(lock)), \
                patch.object(tactical, 'DOCK_SCROLL') as scroll, \
                patch.object(tactical, 'LevelOcr') as level_ocr, \
                patch.object(tactical, 'Ocr') as name_ocr:
            scroll.cal_position.return_value = 1.0
            scroll.edge_threshold = 0.01
            level_ocr.return_value.ocr.return_value = [1]
            name_ocr.return_value.ocr.side_effect = lambda image: [runner.current_target]
            self.assertTrue(runner._tactical_select_priority_ship())

        self.assertEqual(runner.current_target, '安土')
        self.assertEqual(runner.tactical_priority_current, '安土')
        runner.dock_select_confirm.assert_called_once()
        # The first target was rejected on the observed unlocked card; the
        # priority path ignores ordinary favorite and level settings only.
        runner.dock_favourite_set.assert_called_with(enable=False, wait_loading=False)

    def test_locked_but_unselectable_priority_is_bounded_then_next_is_tried(self):
        runner = self.make_runner()
        runner.tactical_priority_names = ('虎', '安土')
        runner.tactical_priority_exhausted = set()
        runner.tactical_priority_started = set()
        runner.tactical_normal_factions = ['royal', 'sakura']
        runner.tactical_normal_filter_settings = runner.dock_filter.settings_default.copy()
        runner.appear = lambda *args, **kwargs: False
        runner.dock_selected = Mock(side_effect=[False, False, False, True])
        runner.dock_select_confirm = Mock()
        runner.interval_clear = Mock()
        runner.dock_filter_set.side_effect = lambda **kwargs: setattr(
            runner, 'current_target', '虎' if kwargs['faction'] == 'royal' else '安土')

        class Card:
            area = (10, 10, 148, 214)

            def crop(self, *args, **kwargs):
                return object()

        with patch.dict(tactical.CATALOG, {
            '虎': {'rarity': 6, 'type': 3, 'faction': 2},
            '安土': {'rarity': 6, 'type': 6, 'faction': 3},
        }, clear=False), \
                patch.object(tactical, 'dock_cards', return_value=[Card()]), \
                patch.object(tactical, 'dock_card_lock', return_value=True), \
                patch.object(tactical, 'DOCK_SCROLL') as scroll, \
                patch.object(tactical, 'LevelOcr') as level_ocr, \
                patch.object(tactical, 'Ocr') as name_ocr:
            scroll.cal_position.return_value = 1.0
            scroll.edge_threshold = 0.01
            level_ocr.return_value.ocr.return_value = [1]
            name_ocr.return_value.ocr.side_effect = lambda image: [runner.current_target]
            self.assertTrue(runner._tactical_select_priority_ship())

        self.assertEqual(runner.tactical_priority_current, '安土')
        self.assertEqual(runner.dock_selected.call_count, 4)
        runner.dock_select_confirm.assert_called_once()

    def test_all_max_priority_target_is_bounded_and_next_run_retries(self):
        runner = self.make_runner()
        runner.tactical_priority_current = '虎'
        runner.tactical_priority_exhausted = set()
        runner.tactical_priority_started = {'虎'}
        runner.dock_select_index = 5
        self.assertTrue(runner._tactical_advance_ship_candidate())
        self.assertEqual(runner.tactical_priority_exhausted, {'虎'})
        self.assertEqual(runner.tactical_priority_started, set())
        self.assertIsNone(runner.tactical_priority_current)
        self.assertEqual(runner.dock_select_index, 0)

    def test_normal_fallback_restores_saved_filters_and_minimum_level(self):
        runner = self.make_runner()
        runner.tactical_priority_filter_changed = True
        runner.tactical_normal_filter_settings = runner.dock_filter.settings_default.copy()
        runner.tactical_normal_factions = ['royal', 'sakura']
        runner.tactical_priority_names = ('虎',)
        runner.tactical_priority_exhausted = set()
        runner.tactical_priority_started = set()
        runner.tactical_dock_filters_initialized = False
        runner._tactical_select_priority_ship = lambda: False
        runner._tactical_restore_priority_filters = tactical.RewardTacticalClass._tactical_restore_priority_filters.__get__(
            runner, tactical.RewardTacticalClass)
        runner._tactical_initialize_dock_filters = Mock()
        runner.appear = lambda button, *args, **kwargs: button is tactical.SKILL_CONFIRM
        runner.loop = lambda **kwargs: iter([None])
        runner.dock_select_one = Mock()
        runner.dock_select_confirm = Mock()
        runner.interval_clear = Mock()
        button = object()
        runner.tactical_dock_buttons = []
        with patch.object(tactical.server, 'server', 'en'), \
                patch.object(tactical, 'CARD_GRIDS', SimpleNamespace(buttons=[button])), \
                patch.object(tactical, 'LevelOcr') as level_ocr:
            level_ocr.return_value.ocr.return_value = [90]
            self.assertTrue(runner.select_suitable_ship())

        runner.dock_filter_set.assert_called_once_with(
            sort='level', index='all', faction=['royal', 'sakura'], rarity='all', extra='no_limit')
        runner.dock_select_one.assert_called_once_with(button)


if __name__ == '__main__':
    unittest.main()
