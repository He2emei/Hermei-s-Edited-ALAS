import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.event.fleet_preparation import EventFleetPreparation, c_roster_matches, event_fleet_stage
from module.exception import RequestHumanTakeover
from module.map.assets import FLEET_PREPARATION
from module.retire.assets import DOCK_EMPTY


FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'prep-alas2-c1.png'
EMPTY_DOCK_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'alas2-c-slot1-carrier-empty.png'
D3_TOTAL_RED_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'd3-total-red-source.png'
D3_TOTAL_GREEN_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'd3-total-green-source.png'
SOURCE = [
    {'name': '苏维埃同盟', 'level': 125},
    {'name': '武藏', 'level': 125},
    {'name': '新泽西', 'level': 125},
    {'name': '关岛', 'level': 125},
    {'name': '威廉D波特', 'level': 125},
    {'name': '莫斯科', 'level': 125},
]


def config_for(stage, *, enabled=True, command='Event', server_name='cn'):
    return SimpleNamespace(
        EventFleet_AutoPrepare=enabled,
        Scheduler_Command=command,
        Campaign_Event='event_20260912_cn',
        Campaign_Name=stage,
        SERVER=server_name,
        Submarine_Fleet=False,
    )


class EventFleetPreparationTest(unittest.TestCase):
    def test_stage_gate_allows_only_event_c_d_and_sp_stages(self):
        for stage in ('C1', 'C3', 'D1', 'D3', 'SP'):
            with self.subTest(stage=stage):
                self.assertEqual(event_fleet_stage(config_for(stage)), stage.lower())
        for stage in ('A1', 'B3', '12-4'):
            with self.subTest(stage=stage):
                self.assertIsNone(event_fleet_stage(config_for(stage)))

    def test_stage_gate_requires_event_task_and_auto_prepare(self):
        self.assertIsNone(event_fleet_stage(config_for('C1', enabled=False)))
        self.assertIsNone(event_fleet_stage(config_for('C1', command='Main')))

    def test_c_roster_matches_one_main_one_auxiliary_and_exact_source_order(self):
        current = [
            {'name': '主力', 'level': 100}, None, None,
            {'name': '唐斯', 'level': 125}, None, None,
        ] + SOURCE

        self.assertTrue(c_roster_matches(current, SOURCE))
        self.assertFalse(c_roster_matches(current[:6] + list(reversed(SOURCE)), SOURCE))
        self.assertFalse(c_roster_matches(current[:6] + [dict(SOURCE[0], level=124)] + SOURCE[1:], SOURCE))
        self.assertFalse(c_roster_matches([
            {'name': '主力', 'level': 100}, {'name': '多余', 'level': 100}, None,
            {'name': '唐斯', 'level': 125}, None, None,
        ] + SOURCE, SOURCE))

    def test_c_roster_requires_exactly_one_main_and_auxiliary_destroyer(self):
        current = [None, None, None, {'name': '威廉D波特', 'level': 125}, None, None] + SOURCE
        self.assertFalse(c_roster_matches(current, SOURCE))

    def test_preparation_rejects_d_and_sp_outside_cn_1280x720(self):
        for stage, server_name, shape in (
                ('D1', 'cn', (720, 1279, 3)),
                ('SP', 'cn', (719, 1280, 3)),
                ('D1', 'en', (720, 1280, 3)),
        ):
            with self.subTest(stage=stage):
                prep = object.__new__(EventFleetPreparation)
                prep.config = config_for(stage, server_name=server_name)
                prep.device = SimpleNamespace(image=np.zeros(shape, dtype='uint8'))
                fleet = SimpleNamespace(is_hard=Mock())
                with self.assertRaises(RequestHumanTakeover):
                    prep.run(fleet, fleet)
                fleet.is_hard.assert_not_called()

    def test_preparation_accepts_known_twelve_level_state_from_fixture(self):
        image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        self.assertEqual(image.shape[:2], (720, 1280))
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(image=cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
                                      screenshot=Mock(), sleep=Mock())
        expected = [125, 0, 0, 100, 0, 0, 125, 125, 125, 125, 125, 120]
        self.assertEqual(prep.empty_slots(),
                         [False, True, True, False, True, True] + [False] * 6)
        self.assertEqual(prep._stable_levels(), expected)
        self.assertEqual(prep.device.screenshot.call_count, 2)

    def test_find_default_main_ship_uses_main_filter_and_reports_real_empty_dock(self):
        image = cv2.imread(str(EMPTY_DOCK_FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(image=image, stuck_record_add=Mock(), screenshot=Mock(), drag=Mock())
        prep.dock_favourite_set = Mock()
        prep.dock_sort_method_dsc_set = Mock()

        def require_main_filter(**kwargs):
            self.assertEqual(kwargs, {'index': 'main', 'faction': 'all'})

        prep.dock_filter_set = Mock(side_effect=require_main_filter)
        with patch('module.event.fleet_preparation.DOCK_SCROLL.set_top') as set_top:
            with patch('module.event.fleet_preparation.dock_cards') as cards:
                with self.assertRaisesRegex(RequestHumanTakeover, 'candidate not found: main ship'):
                    prep._find_ship(None)

        prep.device.stuck_record_add.assert_called_once_with(DOCK_EMPTY)
        prep.device.drag.assert_not_called()
        cards.assert_not_called()
        prep.dock_favourite_set.assert_called_once_with(False)
        prep.dock_filter_set.assert_called_once_with(index='main', faction='all')
        prep.dock_sort_method_dsc_set.assert_called_once_with(True)
        set_top.assert_called_once_with(main=prep)

    def test_find_ship_unknown_geometry_remains_distinct_from_empty_dock(self):
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'),
                                     screenshot=Mock(), drag=Mock())
        prep.appear = Mock(return_value=False)
        prep.dock_favourite_set = Mock()
        prep.dock_filter_set = Mock()
        prep.dock_sort_method_dsc_set = Mock()

        with patch('module.event.fleet_preparation.DOCK_SCROLL.set_top'):
            with patch('module.event.fleet_preparation.dock_cards', return_value=[]):
                with self.assertRaisesRegex(RequestHumanTakeover, 'dock card geometry is unreadable'):
                    prep._find_ship(None)

        prep.device.drag.assert_not_called()

    def test_run_without_submarine_config_does_not_touch_submarine(self):
        prep = object.__new__(EventFleetPreparation)
        prep.config = config_for('D1')
        prep.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'), screenshot=Mock())
        prep._stable_levels = Mock(return_value=[125] * 12)
        prep._stable_total_stats_satisfied = Mock(return_value=True)
        fleet_1 = SimpleNamespace(is_hard=Mock(return_value=True), is_hard_satisfied=Mock(return_value=True),
                                  raise_hard_not_satisfied=Mock())
        fleet_2 = SimpleNamespace(is_hard=Mock(return_value=True), is_hard_satisfied=Mock(return_value=True),
                                  raise_hard_not_satisfied=Mock())

        self.assertTrue(prep.run(fleet_1, fleet_2))
        fleet_1.raise_hard_not_satisfied.assert_called_once()
        fleet_2.raise_hard_not_satisfied.assert_called_once()

    def _real_total_stat_prep(self, *, satisfied=False):
        fixture = D3_TOTAL_GREEN_FIXTURE if satisfied else D3_TOTAL_RED_FIXTURE
        image = cv2.imread(str(fixture), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        prep = object.__new__(EventFleetPreparation)
        prep.config = config_for('D3')
        prep.device = SimpleNamespace(image=image, screenshot=Mock())
        FLEET_PREPARATION.clear_offset()
        prep.device.stuck_record_add = Mock()
        prep._stable_levels = Mock(return_value=[125] * 12)
        return prep

    def test_real_red_total_stat_recommends_both_then_satisfied_frame_passes(self):
        prep = self._real_total_stat_prep()
        self.assertFalse(prep._total_stats_satisfied())
        fleets = [SimpleNamespace(is_hard=Mock(return_value=True),
                                  is_hard_satisfied=Mock(return_value=True),
                                  raise_hard_not_satisfied=Mock()) for _ in range(2)]

        def recommend(_fleet):
            prep.device.image = cv2.cvtColor(cv2.imread(str(D3_TOTAL_GREEN_FIXTURE)), cv2.COLOR_BGR2RGB)

        prep._recommend = Mock(side_effect=recommend)
        self.assertTrue(prep.run(*fleets))
        self.assertEqual(prep._recommend.call_args_list, [((fleet,), {}) for fleet in fleets])
        for fleet in fleets:
            fleet.raise_hard_not_satisfied.assert_called_once()

    def test_real_red_still_red_after_both_recommendations_takes_over_once(self):
        prep = self._real_total_stat_prep()
        fleets = [SimpleNamespace(is_hard=Mock(return_value=True),
                                  is_hard_satisfied=Mock(return_value=True),
                                  raise_hard_not_satisfied=Mock()) for _ in range(2)]
        prep._recommend = Mock()

        with self.assertRaisesRegex(RequestHumanTakeover, 'total stats remain unsatisfied'):
            prep.run(*fleets)
        self.assertEqual(prep._recommend.call_args_list, [((fleet,), {}) for fleet in fleets])
        for fleet in fleets:
            fleet.raise_hard_not_satisfied.assert_not_called()

    def test_actual_green_total_stat_runs_without_recommendation(self):
        prep = self._real_total_stat_prep(satisfied=True)
        fleets = [SimpleNamespace(is_hard=Mock(return_value=True),
                                  is_hard_satisfied=Mock(return_value=True),
                                  raise_hard_not_satisfied=Mock()) for _ in range(2)]
        prep._recommend = Mock()

        self.assertTrue(prep.run(*fleets))
        prep._recommend.assert_not_called()
        for fleet in fleets:
            fleet.raise_hard_not_satisfied.assert_called_once()

    def test_all_red_requirement_text_is_unsatisfied_and_unknown_page_or_color_fails_closed(self):
        prep = self._real_total_stat_prep()
        # The live red frame includes yellow requirements plus aviation red.
        # Recolor all requirement text red; red is still a known unsatisfied
        # state even though the satisfied-yellow evidence disappears.
        y = 549
        crop = prep.device.image[y:y + 50, 120:484]
        red, green, blue = (crop[:, :, i].astype('int16') for i in range(3))
        yellow = (red > 90) & (green > 90) & (blue < 110) & (green > blue * 1.25)
        crop[yellow] = (156, 62, 63)
        self.assertFalse(prep._total_stats_satisfied())

        prep.device.image[:] = 0
        with self.assertRaisesRegex(RequestHumanTakeover, 'outside fleet preparation'):
            prep._total_stats_satisfied()
        FLEET_PREPARATION.clear_offset()
        prep.device.image = cv2.cvtColor(cv2.imread(str(D3_TOTAL_RED_FIXTURE)), cv2.COLOR_BGR2RGB)
        prep.device.image[549:599, 120:484] = (32, 46, 48)
        with self.assertRaisesRegex(RequestHumanTakeover, 'color is unreadable'):
            prep._total_stats_satisfied()

    def test_c_blank_stats_with_yellow_xp_icon_outside_text_crop_fail_closed(self):
        image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(image=cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
                                      stuck_record_add=Mock())
        FLEET_PREPARATION.clear_offset()
        self.assertTrue(prep._at_preparation())
        button_y = FLEET_PREPARATION.button[1]
        prep.device.image[button_y:button_y + 50, 120:484] = (32, 46, 48)
        # The C fixture's yellow XP-book icon remains visible at x497..560.
        self.assertTrue(prep.device.image[button_y:button_y + 50, 497:560, 0].max() > 100)
        with self.assertRaisesRegex(RequestHumanTakeover, 'color is unreadable'):
            prep._total_stats_satisfied()

    def test_c_total_stat_failure_preserves_exact_source_roster_without_filling(self):
        prep = object.__new__(EventFleetPreparation)
        prep.config = config_for('C1')
        prep.config._event_source_roster = SOURCE
        image = cv2.imread(str(D3_TOTAL_RED_FIXTURE), cv2.IMREAD_COLOR)
        prep.device = SimpleNamespace(image=cv2.cvtColor(image, cv2.COLOR_BGR2RGB), screenshot=Mock())
        FLEET_PREPARATION.clear_offset()
        prep.device.stuck_record_add = Mock()
        current = [{'name': '主力', 'level': 100}, None, None,
                   {'name': '唐斯', 'level': 125}, None, None] + SOURCE
        prep.read_roster = Mock(return_value=current)
        prep._fill_slot = Mock()
        prep._clear_fleet = Mock()
        fleets = [SimpleNamespace(is_hard=Mock(return_value=True), raise_hard_not_satisfied=Mock())
                  for _ in range(2)]

        with self.assertRaisesRegex(RequestHumanTakeover, 'C source fleet does not satisfy total-stat'):
            prep.run(*fleets)
        prep._fill_slot.assert_not_called()
        prep._clear_fleet.assert_not_called()
        prep.read_roster.assert_called_once()

    def test_run_with_submarine_config_recommends_and_verifies_it(self):
        prep = object.__new__(EventFleetPreparation)
        prep.config = config_for('SP')
        prep.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'))
        prep._stable_levels = Mock(return_value=[125] * 12)
        prep._stable_total_stats_satisfied = Mock(return_value=True)
        prep._recommend = Mock()
        hard_fleet = lambda: SimpleNamespace(is_hard=Mock(return_value=True),
                                             is_hard_satisfied=Mock(return_value=True),
                                             raise_hard_not_satisfied=Mock())
        submarine = SimpleNamespace(allow=Mock(return_value=True),
                                    is_hard_satisfied=Mock(return_value=False),
                                    raise_hard_not_satisfied=Mock())
        prep.config.Submarine_Fleet = True

        self.assertTrue(prep.run(hard_fleet(), hard_fleet(), submarine))
        prep._recommend.assert_called_once_with(submarine)
        submarine.raise_hard_not_satisfied.assert_called_once()

    def test_c_run_clears_source_ship_before_filling_second_and_preserves_partial_source(self):
        def run_case(current, final, expected_clear, expected_fills):
            prep = object.__new__(EventFleetPreparation)
            prep.config = config_for('C1')
            prep.config._event_source_roster = SOURCE
            prep.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'))
            prep._stable_total_stats_satisfied = Mock(return_value=True)
            prep.read_roster = Mock(side_effect=(current, final))
            events = []
            prep._clear_fleet = Mock(side_effect=lambda fleet, row: events.append(('clear', row)))
            prep._fill_slot = Mock(side_effect=lambda index, ship=None, **kwargs:
                                   events.append(('fill', index, ship)))
            fleet_1 = SimpleNamespace(is_hard=Mock(return_value=True),
                                      raise_hard_not_satisfied=Mock())
            fleet_2 = SimpleNamespace(is_hard=Mock(return_value=True),
                                      raise_hard_not_satisfied=Mock())

            self.assertTrue(prep.run(fleet_1, fleet_2))
            self.assertEqual([event for event in events if event[0] == 'clear'], expected_clear)
            self.assertEqual([event for event in events if event[0] == 'fill'], expected_fills)
            return events

        occupied_source_first = [SOURCE[0], None, None, None, None, None] + [None] * 6
        final_roster = [{'name': '主力', 'level': 100}, None, None,
                        {'name': '唐斯', 'level': 125}, None, None] + SOURCE
        events = run_case(
            occupied_source_first,
            final_roster,
            [('clear', 0)],
            [('fill', index, ship) for index, ship in enumerate(SOURCE, 6)] +
            [('fill', 0, None), ('fill', 5, None)],
        )
        self.assertLess(events.index(('clear', 0)), events.index(('fill', 6, SOURCE[0])))

        partial_source = [{'name': '主力', 'level': 100}, None, None,
                          {'name': '唐斯', 'level': 125}, None, None] + SOURCE[:3] + [None] * 3
        run_case(
            partial_source,
            final_roster,
            [],
            [('fill', 9, SOURCE[3]), ('fill', 10, SOURCE[4]), ('fill', 11, SOURCE[5])],
        )

    def test_clear_fleet_does_not_click_when_stable_levels_are_empty(self):
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(click=Mock(), sleep=Mock(), screenshot=Mock())
        prep._stable_levels = Mock(return_value=[0] * 12)
        fleet = SimpleNamespace(_clear=object())

        prep._clear_fleet(fleet, 0)

        prep.device.click.assert_not_called()

    def test_clear_fleet_clicks_once_and_requires_two_empty_frames(self):
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(click=Mock(), sleep=Mock(), screenshot=Mock())
        prep._stable_levels = Mock(return_value=[125] + [0] * 11)
        prep.levels = Mock(side_effect=([125] + [0] * 5, [0] * 6, [0] * 6))
        prep.empty_slots = Mock(side_effect=([False] * 6 + [True] * 6,
                                             [True] * 12, [True] * 12))
        prep._at_preparation = Mock(return_value=True)
        prep.handle_popup_confirm = Mock(side_effect=(True, False, False, False, False))
        fleet = SimpleNamespace(_clear=object())

        prep._clear_fleet(fleet, 0)

        prep.device.click.assert_called_once_with(fleet._clear)
        self.assertEqual(prep.levels.call_count, 0)
        self.assertEqual(prep.empty_slots.call_count, 3)
        self.assertEqual(prep.handle_popup_confirm.call_count, 4)

    def test_stable_levels_rejects_all_zero_transition_without_empty_slot_templates(self):
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'),
                                      screenshot=Mock(), sleep=Mock())
        prep.levels = Mock(return_value=[0] * 12)
        prep.empty_slots = Mock(return_value=[False] * 12)

        with self.assertRaises(RequestHumanTakeover):
            prep._stable_levels()

        self.assertGreaterEqual(prep.empty_slots.call_count, 2)

    def test_recommend_clicks_advice_when_partial_fleet_is_already_in_use(self):
        prep = object.__new__(EventFleetPreparation)
        prep.device = SimpleNamespace(click=Mock(), sleep=Mock(), screenshot=Mock())
        prep._at_preparation = Mock(return_value=True)
        prep.handle_popup_confirm = Mock(return_value=False)
        advice = object()
        fleet = SimpleNamespace(is_hard=Mock(return_value=True), in_use=Mock(return_value=True), _advice=advice,
                                choose=Mock())

        prep._recommend(fleet)

        prep.device.click.assert_called_once_with(advice)
        fleet.choose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
