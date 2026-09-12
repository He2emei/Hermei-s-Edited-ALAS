import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

import module.config.server as server
from module.event.fleet_source import EventFleetNameOcr, EventFleetSource, normalize_ship_name
from module.exception import RequestHumanTakeover
from module.ocr.ocr import Ocr
from module.retire.card_geometry import dock_cards


FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'source-alas5.png'
PINK_NAME_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'source-alas2-c1.png'
DOCK_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'dock-calibration.png'
DETAIL_FIXTURE = Path(__file__).parent / 'fixtures' / 'event_fleet' / 'detail-calibration.png'


class EventFleetSourceTest(unittest.TestCase):
    def test_normalize_ship_name_only_removes_presentation_noise(self):
        self.assertEqual(normalize_ship_name(' 威廉 ・ D ・ 波特 '), '威廉D波特')
        self.assertEqual(normalize_ship_name('威廉D波特'), '威廉D波特')
        self.assertEqual(normalize_ship_name('新泽西'), '新泽西')

    def test_read_opens_details_only_when_first_read_is_not_valid(self):
        source = object.__new__(EventFleetSource)
        source.device = SimpleNamespace(click=Mock(), image=np.zeros((720, 1280, 3), dtype='uint8'))
        source.ui_ensure = Mock()
        source._select_fleet = Mock()
        source._read_consistent_cards = Mock(side_effect=(
            None,
            (['苏维埃同盟', '武藏', '新泽西', '关岛', '威廉D波特', '莫斯科'], [125] * 6),
        ))

        result = source.read(5)

        source.ui_ensure.assert_called_once()
        source._select_fleet.assert_called_once_with(5)
        detail_button = source.device.click.call_args[0][0]
        self.assertEqual(detail_button.button, (947, 665, 953, 671))
        self.assertEqual([record['side'] for record in result],
                         ['main', 'main', 'main', 'vanguard', 'vanguard', 'vanguard'])
        self.assertEqual([record['name'] for record in result],
                         ['苏维埃同盟', '武藏', '新泽西', '关岛', '威廉D波特', '莫斯科'])
        self.assertEqual([record['level'] for record in result], [125] * 6)

    def test_fleet_choice_coordinates_and_dropdown_pixel_check(self):
        self.assertEqual(EventFleetSource._fleet_choice_point(1), (245, 607))
        self.assertEqual(EventFleetSource._fleet_choice_point(6), (245, 337))

        before = np.zeros((720, 1280, 3), dtype='uint8')
        after = before.copy()
        after[300:630, 200:500] = 20
        self.assertTrue(EventFleetSource._dropdown_visible(before, after))
        self.assertFalse(EventFleetSource._dropdown_visible(before, before))

    def test_read_gates_server_and_screen_before_ui(self):
        source = object.__new__(EventFleetSource)
        source.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype='uint8'))
        source.ui_ensure = Mock()
        old_server = server.server
        server.server = 'en'
        try:
            with self.assertRaises(RequestHumanTakeover):
                source.read(5)
        finally:
            server.server = old_server
        source.ui_ensure.assert_not_called()

    def test_real_fixture_ocr_reads_all_six_expected_names(self):
        image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        source = object.__new__(EventFleetSource)
        source.device = SimpleNamespace(image=image)
        cards = source._read_cards()

        self.assertIsNotNone(cards)
        names, levels = cards
        self.assertEqual(names, ['苏维埃同盟', '武藏', '新泽西', '关岛', '威廉D波特', '莫斯科'])
        self.assertEqual(levels, [125] * 6)

    def test_real_source_fixture_reads_selected_fleet_five_from_bottom_label(self):
        image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        source = object.__new__(EventFleetSource)
        source.device = SimpleNamespace(image=image)

        self.assertEqual(source._read_selected_fleet(), 5)

    def test_real_fixture_ocr_reads_pink_first_name_and_levels(self):
        image = cv2.imread(str(PINK_NAME_FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        source = object.__new__(EventFleetSource)
        source.device = SimpleNamespace(image=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        self.assertEqual(source._read_cards(), (
            ['新泽西', '苏维埃同盟', '阿尔萨斯', '莫斯科', '岛风', '关岛'],
            [125, 125, 125, 125, 120, 125],
        ))

    def test_dock_name_calibration_reads_first_three_source_ships(self):
        image = cv2.imread(str(DOCK_FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        cards = dock_cards(image)
        self.assertEqual(len(cards), 14)

        # card_geometry returns two rows of seven cards. The source ships in
        # this calibration screen are cards 1, 5, and 9 in slot order.
        for index, expected in zip((0, 4, 8), ('新泽西', '武藏', '苏维埃同盟')):
            votes = []
            card = cards[index].area
            for offset in (167, 168, 169):
                area = (card[0] + 15, card[1] + offset,
                        card[2] - 15, card[1] + offset + 19)
                for ocr_class in (Ocr, EventFleetNameOcr):
                    value = ocr_class([area], lang='cnocr',
                                      name='EventDockCalibration').ocr(image)
                    votes.append(normalize_ship_name(value))
            counts = Counter(votes)
            winner, winner_count = counts.most_common(1)[0]
            self.assertEqual(winner, expected)
            self.assertGreaterEqual(winner_count, 2)
            self.assertTrue(len(counts) == 1 or
                            winner_count > counts.most_common(2)[1][1])

    def test_detail_name_vote_has_unique_two_vote_minimum(self):
        image = cv2.imread(str(DETAIL_FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        areas = (
            (210, 88, 400, 115),
            (210, 90, 425, 115),
            (240, 90, 400, 115),
        )
        votes = []
        for area in areas:
            for ocr_class in (Ocr, EventFleetNameOcr):
                value = ocr_class([area], lang='cnocr',
                                  name='EventDetailCalibration').ocr(image)
                votes.append(normalize_ship_name(value))
        counts = Counter(votes)
        winner, winner_count = counts.most_common(1)[0]
        self.assertEqual(winner, '关岛')
        self.assertGreaterEqual(winner_count, 2)
        self.assertTrue(len(counts) == 1 or winner_count > counts.most_common(2)[1][1])


if __name__ == '__main__':
    unittest.main()
