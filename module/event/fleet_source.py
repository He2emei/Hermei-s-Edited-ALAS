from __future__ import annotations

import re
from copy import deepcopy

from module.combat.level import LevelOcr
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Ocr
from module.base.button import Button
from module.retire.dock import Dock
import module.config.server as server
from module.ui.page import page_fleet


FLEET_SELECTOR_CLICK = (220, 622)
FLEET_SELECTOR_X = 245
FLEET_SELECTOR_FIRST_Y = 607
FLEET_SELECTOR_DELTA_Y = 54
# The formation details overlay can cover the upper fleet number. This label
# remains visible in both formation and details modes.
FLEET_NUMBER_AREA = (145, 650, 355, 705)
FLEET_NUMBER_FALLBACK_AREA = (270, 650, 355, 705)
DETAILS_TOGGLE_CLICK = (950, 668)

CARD_X = (62, 248, 435, 686, 873, 1059)
CARD_WIDTH = 156
CARD_NAME_Y = (464, 490)
CARD_LEVEL_Y = (152, 178)
DROPDOWN_DIFF_AREA = (200, 300, 500, 630)


def point_button(x, y, name):
    return Button((x - 3, y - 3, x + 3, y + 3), (0, 0, 0),
                  (x - 3, y - 3, x + 3, y + 3), name=name)


class FleetIndexOcr(Ocr):
    """Read the yellow/grey selected-fleet label with max-RGB preprocessing."""

    def pre_process(self, image):
        return 255 - image.max(axis=2)


class EventFleetNameOcr(Ocr):
    """Read names whose white or pink text is over a card illustration."""

    def pre_process(self, image):
        return 255 - image.max(axis=2)


def normalize_ship_name(name: str) -> str:
    """Normalize presentation noise without changing the ship spelling."""
    name = re.sub(r'\s+', '', str(name or ''))
    name = name.translate(str.maketrans({'・': '·', '･': '·', '．': '·',
                                         '.': '·', '•': '·', '⋅': '·'}))
    # Presentation middle dots are optional in CN UI OCR. Remove them so
    # source, detail, and dock reads compare the same exact ship spelling.
    name = name.replace('·', '')
    # OCR can include card decoration at either edge. Keep Chinese, Latin,
    # and digits; do not perform identity matching or fuzzy correction.
    return re.sub(r'[^\u3400-\u9fffA-Za-z0-9]', '', name)


class EventFleetSource(Dock):
    """Read the six ships in an event formation without changing fleet contents."""

    _READ_ATTEMPTS = 4
    _DETAILS_LOAD_WAIT = 0.4

    @staticmethod
    def _name_areas():
        # Exclude the side ornaments; they are especially harmful to pink
        # names such as 新泽西 while the inner 126px retains the full text.
        return [(x + 15, CARD_NAME_Y[0], x + CARD_WIDTH - 15, CARD_NAME_Y[1]) for x in CARD_X]

    @staticmethod
    def _level_areas():
        return [(x + 77, CARD_LEVEL_Y[0], x + 154, CARD_LEVEL_Y[1]) for x in CARD_X]

    def _read_selected_fleet(self):
        for area, alphabet in (
                (FLEET_NUMBER_AREA, '123456'),
                (FLEET_NUMBER_AREA, None),
                (FLEET_NUMBER_FALLBACK_AREA, '123456'),
                (FLEET_NUMBER_FALLBACK_AREA, None)):
            raw = FleetIndexOcr([area], lang='cnocr', alphabet=alphabet,
                                name='EventFleetSourceSelectedFleet').ocr(self.device.image)
            value = raw[0] if isinstance(raw, list) else raw
            matches = re.findall(r'[1-6]', str(value or ''))
            if len(matches) == 1:
                return int(matches[0])
        return None

    @staticmethod
    def _fleet_choice_point(fleet_index):
        return (FLEET_SELECTOR_X,
                FLEET_SELECTOR_FIRST_Y - (fleet_index - 1) * FLEET_SELECTOR_DELTA_Y)

    @staticmethod
    def _dropdown_visible(before, after):
        if before is None or after is None or before.shape != after.shape:
            return False
        x1, y1, x2, y2 = DROPDOWN_DIFF_AREA
        difference = abs(after[y1:y2, x1:x2].astype('int16')
                         - before[y1:y2, x1:x2].astype('int16'))
        return float(difference.mean()) >= 2.0

    def _ensure_supported_screen(self):
        if server.server != 'cn':
            raise RequestHumanTakeover('Event fleet source requires the CN client')
        image = getattr(self.device, 'image', None)
        if image is None:
            self.device.screenshot()
            image = self.device.image
        if image.shape[:2] != (720, 1280):
            raise RequestHumanTakeover('Event fleet source requires a 1280x720 screen')

    def _select_fleet(self, fleet_index):
        if not isinstance(fleet_index, int) or not 1 <= fleet_index <= 6:
            raise ValueError('fleet_index must be an integer from 1 through 6')

        if self._read_selected_fleet() == fleet_index:
            return

        before = deepcopy(self.device.image)
        self.device.click(point_button(*FLEET_SELECTOR_CLICK, 'EVENT_FLEET_SELECTOR'))
        self.device.sleep(self._DETAILS_LOAD_WAIT)
        self.device.screenshot()
        if not self._dropdown_visible(before, self.device.image):
            raise RequestHumanTakeover('Unable to verify event fleet selector dropdown')

        self.device.click(point_button(*self._fleet_choice_point(fleet_index),
                                        f'EVENT_FLEET_CHOICE_{fleet_index}'))
        for attempt in range(self._READ_ATTEMPTS):
            if attempt:
                self.device.sleep(self._DETAILS_LOAD_WAIT)
                self.device.screenshot()
            if self._read_selected_fleet() == fleet_index:
                return

        raise RequestHumanTakeover(f'Unable to confirm event fleet {fleet_index}')

    def _read_cards(self):
        names = EventFleetNameOcr(self._name_areas(), lang='cnocr', name='EventFleetSourceNames').ocr(self.device.image)
        levels = LevelOcr(self._level_areas(), name='EventFleetSourceLevels').ocr(self.device.image)
        names = [normalize_ship_name(name) for name in names]
        if len(names) != 6 or len(levels) != 6:
            return None
        if not all(names) or not all(isinstance(level, int) and 1 <= level <= 125 for level in levels):
            return None
        return names, levels

    def _read_consistent_cards(self):
        previous = None
        for attempt in range(self._READ_ATTEMPTS):
            if attempt:
                self.device.screenshot()
            current = self._read_cards()
            if current is None:
                previous = None
                continue
            if current == previous:
                return current
            previous = current
        return None

    def read(self, fleet_index: int) -> list[dict]:
        """Read six formation cards in slot order: main fleet first, then vanguard."""
        self._ensure_supported_screen()
        self.ui_ensure(page_fleet)
        self._select_fleet(fleet_index)

        cards = self._read_consistent_cards()
        if cards is None:
            logger.info('Event fleet details are not visible, opening details')
            self.device.click(point_button(*DETAILS_TOGGLE_CLICK, 'EVENT_FLEET_DETAILS'))
            cards = self._read_consistent_cards()
        if cards is None:
            raise RequestHumanTakeover('Unable to read six consistent event fleet cards')

        names, levels = cards
        return [
            {'name': name, 'level': level, 'side': 'main' if index < 3 else 'vanguard'}
            for index, (name, level) in enumerate(zip(names, levels))
        ]
