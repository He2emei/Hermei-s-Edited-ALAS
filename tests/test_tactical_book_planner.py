import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.tactical.book_planner import (
    plan_books,
    remaining_from_projected_counter,
    remaining_to_level10,
)


def book(tier, genre=1, exp=True, count=None):
    return SimpleNamespace(tier=tier, genre=genre, exp=exp, count=count,
                           exp_value={1: 100, 2: 300, 3: 800, 4: 1500}[tier])


class TacticalBookPlannerTest(unittest.TestCase):
    def test_remaining_xp_uses_current_level_denominator(self):
        self.assertEqual(remaining_to_level10(150, 1400), 16850)
        self.assertIsNone(remaining_to_level10(10, 999))

    def test_projected_counter_restores_selected_book_and_green_remainder(self):
        self.assertEqual(
            remaining_from_projected_counter(0, 100, 2200, 3000),
            18500,
        )
        self.assertIsNone(remaining_from_projected_counter(0, 100, 999, 3000))
        self.assertIsNone(remaining_from_projected_counter(0, 2200, 2200, 3000))
        self.assertIsNone(remaining_from_projected_counter(0, 100, 100, 3000))
        self.assertIsNone(remaining_from_projected_counter(0, 0, 100, 20000))

    def test_same_color_values_and_overflow_are_optimized(self):
        result = plan_books(3000, [book(1), book(2), book(3), book(4)], 1)
        self.assertTrue(result.complete)
        self.assertEqual(result.total_xp, 3000)
        self.assertEqual(result.total_hours, 12)
        self.assertEqual([item.tier for item in result.books], [4])

    def test_counts_are_finite_and_longest_course_is_first(self):
        result = plan_books(3600, [book(1), book(2), book(3), book(4)], 1,
                            counts={1: 4, 2: 1, 3: 3, 4: 1})
        self.assertTrue(result.complete)
        self.assertEqual(result.total_xp, 3600)
        self.assertEqual(result.total_hours, 18)
        self.assertEqual([item.tier for item in result.books], [4, 2, 1])

    def test_unknown_counts_use_each_visible_book_once(self):
        result = plan_books(1000, [book(1), book(1), book(2)], 1)
        self.assertFalse(result.complete)
        self.assertEqual(result.total_xp, 750)
        self.assertEqual(result.total_hours, 8)
        self.assertEqual(result.courses, 3)

    def test_planner_rejects_remaining_outside_supported_range(self):
        result = plan_books(18501, [book(4)], 1)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, 'invalid remaining XP')

    def test_off_color_unknown_and_invalid_books_are_rejected(self):
        result = plan_books(100, [book(4, genre=2), book(3, exp=False), book(1)], 1)
        self.assertTrue(result.complete)
        self.assertEqual(result.books[0].tier, 1)
        self.assertEqual(plan_books(100, [book(1)], None).reason,
                         'skill color is unknown')

    def test_saved_png_reads_projected_skill_and_visible_counts(self):
        import cv2 as cv
        from module.tactical.tactical_class import BOOK_COUNT_OCR, PROJECTED_SKILL_EXP

        path = Path(__file__).parents[1].parent / 'code_workflow' / 'evidence' / '2026-09-08' / 'tactical-books.png'
        image = cv.cvtColor(cv.imread(str(path)), cv.COLOR_BGR2RGB)
        self.assertEqual(PROJECTED_SKILL_EXP.ocr(image), (0, 100, 2200))
        counts = BOOK_COUNT_OCR.ocr(image)
        self.assertEqual([counts[i] for i in (0, 1, 2, 3, 6, 9)],
                         [4, 10, 217, 456, 497, 249])

    def test_optimizer_cancels_when_fresh_books_have_no_same_color(self):
        from module.tactical import tactical_class as tactical

        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=object(), click=lambda button: setattr(runner, 'clicked', button))
        off_color = book(4, genre=2)
        off_color.check_selected = lambda image: True
        runner.books = [off_color]
        runner.tactical_skill_genre = 1
        runner._tactical_books_get = lambda: True
        runner._tactical_book_optimization_enabled = lambda: True
        with patch.object(tactical, 'PROJECTED_SKILL_EXP', SimpleNamespace(ocr=lambda image: (0, 100, 2200))), \
                patch.object(tactical, 'TACTICAL_CLASS_CANCEL', 'cancel'):
            self.assertFalse(runner._tactical_books_choose())
        self.assertEqual(runner.clicked, 'cancel')

    def test_optimizer_cancels_on_invalid_counter(self):
        from module.tactical import tactical_class as tactical

        selected = book(4, genre=1, count=1)
        selected.check_selected = lambda image: True
        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=object(), click=lambda button: setattr(runner, 'clicked', button))
        runner.books = [selected]
        runner.tactical_skill_genre = 1
        runner._tactical_books_get = lambda: True
        runner._tactical_book_optimization_enabled = lambda: True
        with patch.object(tactical, 'PROJECTED_SKILL_EXP', SimpleNamespace(ocr=lambda image: None)), \
                patch.object(tactical, 'TACTICAL_CLASS_CANCEL', 'cancel'):
            self.assertFalse(runner._tactical_books_choose())
        self.assertEqual(runner.clicked, 'cancel')

    def test_optimizer_cancels_when_selected_book_is_missing(self):
        from module.tactical import tactical_class as tactical

        missing = book(4, genre=1, count=1)
        missing.check_selected = lambda image: False
        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=object(), click=lambda button: setattr(runner, 'clicked', button))
        runner.books = [missing]
        runner.tactical_skill_genre = 1
        runner._tactical_books_get = lambda: True
        runner._tactical_book_optimization_enabled = lambda: True
        with patch.object(tactical, 'TACTICAL_CLASS_CANCEL', 'cancel'):
            self.assertFalse(runner._tactical_books_choose())
        self.assertEqual(runner.clicked, 'cancel')

    def test_max_big_book_refreshes_to_nonmax_before_planning(self):
        from module.tactical import tactical_class as tactical

        big = book(4, genre=1, count=1)
        big.exp_value = 3000
        small = book(1, genre=1, count=1)
        small.exp_value = 150
        selected = {'book': big}
        big.check_selected = lambda image: selected['book'] is big
        small.check_selected = lambda image: selected['book'] is small
        refreshes = {'count': 0}

        def refresh(*, skip_first_screenshot=True):
            refreshes['count'] += 1
            if refreshes['count'] == 2:
                selected['book'] = small
            return True

        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=object(), click=lambda button: setattr(runner, 'clicked', button))
        runner.books = [big, small]
        runner.tactical_skill_genre = 1
        runner._tactical_books_get = refresh
        runner._tactical_book_optimization_enabled = lambda: True
        runner._tactical_book_select = lambda item: setattr(runner, 'chosen', item)
        projected = iter([tactical.PROJECTED_MAX, (0, 100, 2200)])
        with patch.object(tactical, 'PROJECTED_SKILL_EXP', SimpleNamespace(ocr=lambda image: next(projected))), \
                patch.object(tactical, 'TACTICAL_CLASS_START', 'start'):
            self.assertTrue(runner._tactical_books_choose())
        self.assertEqual(refreshes['count'], 2)
        self.assertIs(runner.chosen, big)
        self.assertEqual(runner.clicked, 'start')

    def test_all_max_advances_in_screen_order_with_bound(self):
        from module.tactical import tactical_class as tactical

        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.dock_select_index = 0
        runner.tactical_dock_buttons = [object()] * 14
        runner.tactical_dock_page_count = 1
        self.assertTrue(runner._tactical_advance_ship_candidate())
        self.assertEqual(runner.dock_select_index, 1)
        for _ in range(len(runner.tactical_dock_buttons) - 2):
            self.assertTrue(runner._tactical_advance_ship_candidate())
        self.assertTrue(runner._tactical_advance_ship_candidate())
        self.assertEqual(runner.dock_select_index, len(runner.tactical_dock_buttons))
        runner.tactical_dock_page_count = 40
        self.assertFalse(runner._tactical_advance_ship_candidate())

    def test_dock_filters_are_initialized_once_across_candidate_continuations(self):
        from module.tactical import tactical_class as tactical

        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(AddNewStudent_Favorite=False)
        runner.dock_filter = SimpleNamespace(settings=[('faction', 'all'), ('faction', 'royal'),
                                                        ('faction', 'meta')])
        runner.dock_favourite_set = Mock()
        runner.dock_filter_set = Mock()

        runner._tactical_initialize_dock_filters()
        runner._tactical_initialize_dock_filters()

        runner.dock_favourite_set.assert_called_once_with(enable=False, wait_loading=False)
        runner.dock_filter_set.assert_called_once_with(faction=['royal'])
        self.assertTrue(runner.tactical_dock_filters_initialized)

    def test_optimized_book_loading_waits_for_full_stock_signature(self):
        from module.tactical import tactical_class as tactical

        class FakeSelectedGrids(list):
            @property
            def count(self):
                return len(self)

            def select(self, valid=True):
                return self

        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=0, screenshot=lambda: setattr(runner.device, 'image', 1),
                                        sleep=lambda seconds: None)
        runner.appear = lambda *args, **kwargs: True
        runner.handle_info_bar = lambda: None
        runner._tactical_book_signature = None
        frames = iter([0, 1, 1])

        def make_book(image, button):
            frame = next(frames)
            return SimpleNamespace(genre=1, tier=4, count=None, exp=True, frame=frame)

        def read_counts(image):
            return [0 if image == 0 else 10]

        with patch.object(tactical, 'SelectedGrids', FakeSelectedGrids), \
                patch.object(tactical, 'BOOKS_GRID', SimpleNamespace(buttons=['book'])), \
                patch.object(tactical, 'Book', side_effect=make_book), \
                patch.object(tactical, 'BOOK_COUNT_OCR', SimpleNamespace(ocr=read_counts)):
            result = runner._tactical_books_get()

        self.assertEqual(result[0].count, 10)
        self.assertEqual(runner.device.image, 1)

    def test_locked_tail_is_excluded_from_ship_candidates(self):
        from module.tactical import tactical_class as tactical

        levels = [120, 120, 0, 120, 120]
        self.assertEqual(
            list(tactical.RewardTacticalClass._tactical_available_ship_indices(levels)),
            [0, 1],
        )
        self.assertEqual(
            list(tactical.RewardTacticalClass._tactical_available_ship_indices(levels, 1)),
            [1],
        )

    def test_optimizer_progresses_with_same_color_stock(self):
        from module.tactical import tactical_class as tactical

        selected = book(4, genre=1, count=1)
        selected.exp_value = 3000
        selected.check_selected = lambda image: True
        runner = tactical.RewardTacticalClass.__new__(tactical.RewardTacticalClass)
        runner.config = SimpleNamespace(Tactical_OptimizeBooks=True)
        runner.device = SimpleNamespace(image=object(), click=lambda button: setattr(runner, 'clicked', button))
        runner.books = [selected]
        runner.tactical_skill_genre = 1
        runner._tactical_books_get = lambda: True
        runner._tactical_book_optimization_enabled = lambda: True
        runner._tactical_book_select = lambda item: setattr(runner, 'chosen', item)
        with patch.object(tactical, 'PROJECTED_SKILL_EXP', SimpleNamespace(ocr=lambda image: (0, 100, 2200))), \
                patch.object(tactical, 'TACTICAL_CLASS_START', 'start'):
            self.assertTrue(runner._tactical_books_choose())
        self.assertIs(runner.chosen, selected)
        self.assertEqual(runner.clicked, 'start')


if __name__ == '__main__':
    unittest.main()
