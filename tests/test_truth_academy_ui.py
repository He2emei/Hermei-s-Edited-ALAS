import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.coalition import ui
from module.coalition import truth_academy
from module.coalition.truth_academy import TruthAcademyReader
from module.exception import CampaignNameError, RequestHumanTakeover


EVIDENCE = Path(r'E:\Project\AzurLanAutoScript_Test\code_workflow\evidence\2026-11-24-new-event-and-recovery')


def load(name):
    return np.asarray(Image.open(EVIDENCE / name).convert('RGB'))


class TestTruthAcademyRecognition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = TruthAcademyReader()

    def test_normal_base_and_preparation_offline(self):
        self.assertEqual(self.reader.read(load('normal-base-after.png')), 'main')
        prep = load('normal-prep-2.png')
        self.assertEqual(self.reader.read(prep), 'normal_preparation')
        self.assertEqual(self.reader.read_fleet_mode(prep), 'multi')
        ready = load('normal-ready-party.png')
        self.assertEqual(self.reader.read(ready), 'normal_preparation')
        self.assertEqual(self.reader.read_fleet_mode(ready), 'single')

    def test_hard_prep_and_normal_cross_rejection(self):
        hard = load('hard-prep-2.png')
        normal = load('normal-prep-2.png')
        self.assertEqual(self.reader.read(hard), 'hard_preparation')
        self.assertEqual(self.reader.read_fleet_mode(hard), 'multi')
        self.assertEqual(self.reader.read(normal), 'normal_preparation')
        self.assertNotEqual(self.reader.read(hard), self.reader.read(normal))

    def test_easy_preparation_and_unrelated_pages_rejected(self):
        self.assertEqual(self.reader.read(load('event-easy-2.png')), 'simple_preparation')
        self.assertEqual(self.reader.read_fleet_mode(load('event-easy-2.png')), 'single')
        self.assertEqual(self.reader.read(load('hard-prep-2.png')), 'hard_preparation')
        self.assertEqual(self.reader.read(load('normal-base-after.png')[:, ::-1]), 'unknown')

    def test_zero_level_requires_empty_slot_icon_and_rows_are_covered(self):
        image = load('normal-prep-2.png')
        values = [125, 0, 125, 0, 125, 120]
        with patch('module.coalition.truth_academy.Digit') as digit, \
                patch('module.coalition.truth_academy.TRUTH_EMPTY_SLOT.match', return_value=True) as plus:
            digit.return_value.ocr.return_value = values
            self.assertEqual(self.reader.read_fleet_levels(image), tuple(values))
            digit.assert_called_once_with(
                truth_academy.TRUTH_LEVEL_ROIS, name='TRUTH_FLEET_LEVELS', lang='azur_lane',
                letter=(214, 232, 255), threshold=128)
            self.assertEqual(plus.call_count, 2)
        with patch('module.coalition.truth_academy.Digit') as digit, \
                patch('module.coalition.truth_academy.TRUTH_EMPTY_SLOT.match', return_value=False):
            digit.return_value.ocr.return_value = values
            self.assertIsNone(self.reader.read_fleet_levels(image))
        for values in ([0, 0, 0, 125, 125, 120], [125, 125, 125, 0, 0, 0],
                       [126, 125, 125, 125, 125, 120]):
            with patch('module.coalition.truth_academy.Digit') as digit, \
                    patch('module.coalition.truth_academy.TRUTH_EMPTY_SLOT.match', return_value=True):
                digit.return_value.ocr.return_value = values
                self.assertIsNone(self.reader.read_fleet_levels(image))

    def test_real_normal_party_levels_and_empty_slot_plus(self):
        ready_images = [load('normal-ready-party.png'), load('recommended-1.png')]
        empty = load('normal-prep-2.png')
        hard_empty = load('hard-prep-2.png')
        for name, image in zip(('normal-ready-party.png', 'recommended-1.png', 'normal-prep-2.png',
                                'hard-prep-2.png'), ready_images + [empty, hard_empty]):
            self.assertIn(self.reader.read(image),
                          ('simple_preparation', 'normal_preparation', 'hard_preparation'), name)
        # Warm the staged templates before switching to Original for its native OCR model files.
        truth_academy.TRUTH_EMPTY_SLOT.ensure_template()
        old_cwd = Path.cwd()
        original_cwd = Path(r'E:\Project\AzurLanAutoScript_Test\AzurLaneAutoScript-Original')
        try:
            import os
            os.chdir(str(original_cwd))
            expected = (125, 125, 125, 125, 125, 120)
            for image in ready_images:
                self.assertEqual(self.reader.read_fleet_levels(image), expected)
            self.assertIsNone(self.reader.read_fleet_levels(empty))
            self.assertIsNone(self.reader.read_fleet_levels(hard_empty))
            self.assertTrue(all(
                truth_academy.TRUTH_EMPTY_SLOT.match(
                    empty, offset=(88 * i - 8, -5, 88 * i + 8, 5), similarity=0.90)
                for i in range(6)
            ))
            self.assertTrue(all(
                truth_academy.TRUTH_EMPTY_SLOT.match(
                    hard_empty, offset=(88 * i - 8, -5, 88 * i + 8, 5), similarity=0.90)
                for i in range(6)
            ))
        finally:
            os.chdir(str(old_cwd))

    def test_entrance_and_battle_count_scope(self):
        base = load('normal-base-after.png')
        self.assertEqual(ui.CoalitionUI.coalition_get_entrance('coalition_20261124', 'normal'),
                         ui.TRUTH_NORMAL)
        self.assertTrue(ui.TRUTH_HARD.match(base, offset=0, similarity=0.90))
        self.assertEqual(ui.CoalitionUI.coalition_get_battles('coalition_20261124', 'easy'), 1)
        self.assertEqual(ui.CoalitionUI.coalition_get_battles('coalition_20261124', 'normal'), 2)
        self.assertEqual(ui.CoalitionUI.coalition_get_entrance('coalition_20261124', 'hard'),
                         ui.TRUTH_HARD)
        self.assertEqual(ui.CoalitionUI.coalition_get_battles('coalition_20261124', 'hard'), 3)
        with self.assertRaises(CampaignNameError):
            ui.CoalitionUI.coalition_get_entrance('coalition_20261124', 'sp')
        self.assertEqual(ui.CoalitionUI.coalition_get_entrance('coalition_20260723', 'easy'),
                         ui.HORROR_EASY)


class FakeReader:
    def __init__(self, pages, modes, levels):
        self.pages, self.modes, self.levels = pages, modes, levels
        self.index = 0

    def _index(self, image, seq):
        return min(int(image[0, 0, 0]), len(seq) - 1)

    def read(self, image):
        return self.pages[self._index(image, self.pages)]

    def read_fleet_mode(self, image):
        return self.modes[self._index(image, self.modes)]

    def read_fleet_levels(self, image):
        return self.levels[self._index(image, self.levels)]


class FakeDevice:
    def __init__(self, frames):
        self.frames = frames
        self.image = frames[0]
        self.index = 0
        self.clicks = []

    def screenshot(self):
        self.image = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1

    def click(self, button):
        from module.base.button import Button
        assert isinstance(button, Button), 'native Device.click requires Button, not a tuple'
        assert len(button.button) == 4
        self.clicks.append(button.name)


class TestTruthAcademyFleetSafety(unittest.TestCase):
    def make_ui(self, stage, mode, page='normal_preparation', levels=(125, 125, 125, 125, 125, 120), repeat=6):
        obj = object.__new__(ui.CoalitionUI)
        obj.config = SimpleNamespace(SERVER='cn')
        obj.device = FakeDevice([np.full((720, 1280, 3), i, dtype=np.uint8) for i in range(repeat)])
        obj._stage, obj._mode, obj._page, obj._levels = stage, mode, page, levels
        return obj

    def run_with_reader(self, obj, pages, modes, levels):
        fake = FakeReader(pages, modes, levels)
        with patch.object(ui, 'TruthAcademyReader', return_value=fake):
            return obj._truth_handle_fleet_preparation(obj._stage, obj._mode)

    def test_single_fleet_returns_without_selector_click(self):
        obj = self.make_ui('normal', 'single')
        self.run_with_reader(obj, ['normal_preparation'], ['single'], [(125, 125, 125, 125, 125, 120)])
        self.assertEqual(obj.device.clicks, [])

    def test_multi_to_single_is_bounded_and_validated(self):
        obj = self.make_ui('normal', 'single')
        # initial two frames are multi; selector click changes subsequent state to single.
        fake = FakeReader(['normal_preparation'], ['multi', 'multi', 'single', 'single'],
                          [(125, 125, 125, 125, 125, 120)])
        fake._index = lambda image, seq: 0 if image[0, 0, 0] < 2 else min(image[0, 0, 0], len(seq) - 1)
        with patch.object(ui, 'TruthAcademyReader', return_value=fake):
            self.assertTrue(obj._truth_handle_fleet_preparation('normal', 'single'))
        self.assertEqual(obj.device.clicks, ['TRUTH_SELECT_SINGLE'])

    def test_unknown_changing_and_unsupported_multi_never_click(self):
        for modes in (['unknown'], ['multi', 'single']):
            obj = self.make_ui('normal', 'single')
            with self.assertRaises(RequestHumanTakeover):
                self.run_with_reader(obj, ['normal_preparation'], modes, [(125, 125, 125, 125, 125, 120)])
            self.assertEqual(obj.device.clicks, [])
        obj = self.make_ui('normal', 'multi')
        with self.assertRaises(RequestHumanTakeover):
            self.run_with_reader(obj, ['normal_preparation'], ['single'], [(125, 125, 125, 125, 125, 120)])
        self.assertEqual(obj.device.clicks, [])

    def test_invalid_party_and_wrong_page_fail_closed(self):
        invalid = None
        obj = self.make_ui('normal', 'single')
        with self.assertRaises(RequestHumanTakeover):
            self.run_with_reader(obj, ['normal_preparation'], ['single'], [invalid])
        obj = self.make_ui('normal', 'single')
        with self.assertRaises(RequestHumanTakeover):
            self.run_with_reader(obj, ['unknown'], ['single'], [(125, 125, 125, 125, 125, 120)])
        self.assertEqual(obj.device.clicks, [])

    def test_wrong_server_and_easy_multi_refused(self):
        obj = self.make_ui('easy', 'single')
        obj.config.SERVER = 'en'
        with self.assertRaises(RequestHumanTakeover):
            obj._truth_handle_fleet_preparation('easy', 'single')
        obj.config.SERVER = 'cn'
        with self.assertRaises(RequestHumanTakeover):
            self.run_with_reader(obj, ['simple_preparation'], ['multi'], [(125, 125, 125, 125, 125, 120)])
        self.assertEqual(obj.device.clicks, [])

    def test_normal_stage_requested_on_hard_page_fails_without_click(self):
        obj = self.make_ui('normal', 'single')
        with self.assertRaises(RequestHumanTakeover):
            self.run_with_reader(obj, ['hard_preparation'], ['multi'], [None])
        self.assertEqual(obj.device.clicks, [])


if __name__ == '__main__':
    unittest.main()
