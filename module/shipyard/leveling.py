"""Use the game's XP preview to meet a verified shipyard level gate."""
import re

import cv2
import numpy as np

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Ocr
from module.os.training import TrainingFleetManager
from module.os.training_ui import CATALOG, FACTIONS, FILTER_FACTIONS, DOCK_SCROLL, point_button
from module.ui.page import page_dock


class LevelGainOcr(Ocr):
    def pre_process(self, image):
        im = image.astype('int32')
        green = (im[:, :, 1] > 180) & (im[:, :, 1] > im[:, :, 0] * 1.15) & (im[:, :, 1] > im[:, :, 2] * 1.2)
        # Remove the first connected glyph (+). The CN model drops the thin 1
        # in +10; the game's digit model recognizes 10 but has no plus glyph.
        occupied = np.flatnonzero(green.any(axis=0))
        if occupied.size:
            gaps = np.flatnonzero(np.diff(occupied) > 1)
            if not gaps.size:
                raise RequestHumanTakeover('Incomplete level gain glyphs')
            green[:, :occupied[gaps[0]] + 1] = False
        return np.where(green, 0, 255).astype('uint8')


def level_gain(image):
    text = LevelGainOcr((397, 185, 575, 218), alphabet='0123456789ID', name='ShipyardLevelGain').ocr(image)
    text = text.replace('I', '1').replace('D', '0')
    if not text:
        return 0
    if not re.fullmatch(r'\d{1,3}', text) or int(text) > 124:
        raise RequestHumanTakeover('Unknown shipyard XP preview: ' + text)
    return int(text)


def book_counts(image):
    texts = Ocr([(671, 330, 737, 365), (671, 430, 737, 465),
                 (380, 348, 427, 370), (380, 448, 427, 470)],
                alphabet='0123456789', name='ShipyardBooks').ocr(image)
    if any(not re.fullmatch(r'\d{1,4}', t) for t in texts):
        raise RequestHumanTakeover('Cannot read experience book quantities')
    values = tuple(map(int, texts))
    if any(v > 3000 for v in values) or any(values[i] > values[i + 2] for i in (0, 1)):
        raise RequestHumanTakeover('Invalid experience book quantities')
    return values


class ShipyardLeveler(TrainingFleetManager):
    def _book_dialog(self):
        template = cv2.imread('./assets/cn/shipyard_auto/level_title.png')
        template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        return cv2.matchTemplate(self.device.image[108:151, 291:490], template,
                                 cv2.TM_CCOEFF_NORMED).max() > 0.94

    def _book_click(self, x, y, name):
        if not self._book_dialog():
            raise RequestHumanTakeover('Experience book dialog is not visible')
        self.device.click(point_button(x, y, name))
        self.device.sleep(0.3)
        self.device.screenshot()

    def _set_books(self, tier, target, base_level=None):
        """Only +/-1 and +/-10; verify each change rather than trusting click counts."""
        for _ in range(330):
            before = book_counts(self.device.image)[tier]
            if before == target:
                return before
            diff = target - before
            step = 10 if abs(diff) >= 10 else 1
            x = (889 if step == 10 else 808) if diff > 0 else (518 if step == 10 else 601)
            self._book_click(x, 344 + 100 * tier, 'SHIPYARD_BOOK_ADJUST')
            after = book_counts(self.device.image)[tier]
            if after != before + (step if diff > 0 else -step):
                # The game caps a book preview at the current level cap. A
                # doubling probe may reach that cap before its requested count.
                if diff > 0 and before <= after < before + step and base_level is not None \
                        and base_level + level_gain(self.device.image) == 100:
                    return after
                raise RequestHumanTakeover('Experience book selection did not match requested step')
            self.device.click_record_clear()  # A verified quantity change is progress.
        raise RequestHumanTakeover('Experience book selection exceeded its bound')

    def meet_level(self, name, target):
        if name not in CATALOG or not 1 <= target <= 100:
            raise RequestHumanTakeover('Unverified shipyard level target')
        data = CATALOG[name]
        self.ui_ensure(page_dock)
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set(False)
        side = 'main' if data['type'] in (4, 5, 6, 7, 10, 12, 13) else 'vanguard'
        self.dock_filter_set(index=side, faction=FILTER_FACTIONS[FACTIONS[data['faction']]])
        DOCK_SCROLL.set_top(main=self)
        self.ship_info_enter(self._scan_selection(name), long_click=False)
        ship = self.read_ship()
        if ship.name != name:
            raise RequestHumanTakeover('Shipyard level target identity changed')
        if ship.level >= target:
            return True
        self.device.click(point_button(859, 293, 'SHIPYARD_LEVEL_OPEN'))
        self._wait(self._book_dialog, 'experience books')
        self._book_click(430, 553, 'SHIPYARD_BOOK_CLEAR')
        original = book_counts(self.device.image)
        if original[:2] != (0, 0):
            raise RequestHumanTakeover('Cannot clear experience book preview')
        # Prefer plentiful T1 books. Search the smallest quantity whose preview
        # reaches the gate, falling back to T2 only if all T1 are insufficient.
        for tier in (0, 1):
            stock = original[tier + 2]
            if not stock:
                continue
            low, high = 0, min(1, stock)
            while True:
                high = self._set_books(tier, high, base_level=ship.level)
                if ship.level + level_gain(self.device.image) >= target:
                    break
                if high == stock:
                    low = high
                    break
                low, high = high, min(stock, high * 2)
            if low == stock:
                continue
            while high - low > 1:
                middle = (low + high) // 2
                self._set_books(tier, middle)
                if ship.level + level_gain(self.device.image) >= target:
                    high = middle
                else:
                    low = middle
            self._set_books(tier, high)
            selected = book_counts(self.device.image)
            expected = ship.level + level_gain(self.device.image)
            if not target <= expected <= 100 or selected[2:] != original[2:]:
                raise RequestHumanTakeover('Experience book preview failed final validation')
            logger.info(f'Shipyard level: {name} {ship.level}->{expected}, gate={target}, T1={selected[0]}, T2={selected[1]}')
            self._book_click(887, 553, 'SHIPYARD_BOOK_CONFIRM')
            remaining = (0, 0, original[2] - selected[0], original[3] - selected[1])
            self._wait(lambda: self._book_dialog() and book_counts(self.device.image) == remaining,
                       'experience book inventory deduction')
            self._book_click(986, 132, 'SHIPYARD_BOOK_CLOSE')
            actual = self.read_ship()
            if actual.name != name or actual.level != expected:
                raise RequestHumanTakeover('Experience book result differs from preview')
            return True
        self._book_click(986, 132, 'SHIPYARD_BOOK_CLOSE')
        logger.warning(f'Shipyard books insufficient to reach {name} level {target}')
        return False
