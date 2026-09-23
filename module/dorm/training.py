"""Daily CN first-floor submarine maintenance; resting ships are never edited."""
from datetime import datetime
from pathlib import Path

import cv2

from module.base.timer import Timer
from module.combat.level import LevelOcr
from module.dorm.training_policy import plan_dorm_rotation, should_awaken_in_dorm
from module.equipment.assets import EQUIPMENT_OPEN
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Ocr, DigitCounter
from module.os.training_policy import decide_trainability
from module.os.training_ui import TrainingShipInspector, point_button, catalog_name
from module.retire.card_geometry import dock_cards
from module.retire.dock import DOCK_SCROLL, OCR_DOCK_SELECTED
from module.retire.assets import DOCK_CHECK
from module.ui.assets import BACK_ARROW
from module.ui.page import page_dorm
from module.ui.scroll import Scroll


ASSETS = Path('./assets/cn/dorm_training')
DORM_COUNT = DigitCounter([(972, 82, 1040, 115)], letter=(210, 210, 210), name='DormTrainingCount')
# The dock footer hides ~14px of the thumb at its bottom endpoint.
# Both endpoint detection and dragging must accept the observed 0.945 position.
DORM_SCROLL = Scroll(DOCK_SCROLL.area, DOCK_SCROLL.color, name='DORM_DOCK_SCROLL')
DORM_SCROLL.edge_threshold = DORM_SCROLL.drag_threshold = 0.08

TRAINING_HEADER_AREA = (125, 140, 435, 193)
ROSTER_CLOSE_AREA = (1110, 80, 1155, 122)
# Used when the close icon itself cannot be read; verified against live closes.
ROSTER_CLOSE_FALLBACK = point_button(1133, 100, 'DORM_TRAINING_CLOSE')
# Interval between two "close the roster" clicks, the panel needs a moment to close.
roster_close_timer = Timer(2, count=0)

_TEMPLATES = {}


def rgb_template(path):
    """Load a local asset as RGB, the colour space of Device.image. Cached."""
    key = str(path)
    if key not in _TEMPLATES:
        template = cv2.imread(key)
        _TEMPLATES[key] = cv2.cvtColor(template, cv2.COLOR_BGR2RGB) if template is not None else None
    return _TEMPLATES[key]


def match_in_region(image, template, area):
    """Best normalised template match of `template` inside `area` of an RGB screenshot.

    Returns:
        tuple: (score, (x, y)) of the best match, (0.0, None) when the region is too small.
    """
    x1, y1, x2, y2 = area
    region = image[y1:y2, x1:x2]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return 0.0, None
    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    return float(score), (x1 + location[0], y1 + location[1])


def region_similarity(image, template, area):
    """Best normalised template score of `template` inside `area` of an RGB screenshot."""
    return match_in_region(image, template, area)[0]


def locate_roster_close(image, similarity=0.9):
    """Locate the close icon of the first-floor training roster, None when absent.

    The icon is matched, not assumed: the returned button is the centre of the matched
    icon, so a panel that shifts by a few pixels still closes. The icon is the roster's
    own close button, the same on the training tab and on the rest tab, and a rest tab
    roster does not show the training header. Of the 1611 archived crash frames of this
    checkout (2025-12 to 2026-09) only the roster draws this icon in this region.
    """
    template = rgb_template(ASSETS / 'roster_close.png')
    if template is None:
        return None
    score, location = match_in_region(image, template, ROSTER_CLOSE_AREA)
    if score <= similarity:
        return None
    height, width = template.shape[:2]
    return point_button(location[0] + width // 2, location[1] + height // 2, 'DORM_TRAINING_CLOSE')


def dismiss_training_roster(ui):
    """Close the dorm training roster while it covers the screen.

    The roster is a modal panel that hides DORM_CHECK and has no HOME button, so while
    it is open no page matches and every task dies with GamePageUnknownError. It survives
    an interrupted task, and nothing else in Alas closes it, so it is closed here, from
    the page poll, for every task.

    The click is repeated while the panel is still on the display, because a tap can be
    swallowed by the game (live 2026-09-24 03:49:29, the roster stayed open for minutes
    after a tap that the device confirmed). There is no attempt limit: a roster that the
    game will not close is a hung client, and the twelve-click protection of the device
    then restarts the app, which is the only other way out. The interval only keeps the
    panel from being clicked twice while it is closing.
    """
    if getattr(ui.config, 'SERVER', None) != 'cn':
        return False
    if not roster_close_timer.reached():
        return False

    button = locate_roster_close(ui.device.image)
    if button is None:
        return False

    logger.info(f'Dorm training roster is covering the screen, close it: {button}')
    ui.device.click(button)
    roster_close_timer.reset()
    return True


class DormTraining(TrainingShipInspector):
    def _wait(self, predicate, description):
        for _ in range(35):
            self.device.screenshot()
            if predicate():
                self.device.sleep(0.3)
                self.device.screenshot()
                if predicate():
                    return
            self.device.sleep(0.15)
        raise RequestHumanTakeover('Dorm training timeout: ' + description)

    def _training_visible(self):
        template = rgb_template(ASSETS / 'training_header.png')
        if template is None:
            raise RequestHumanTakeover('Dorm training header asset missing')
        return region_similarity(self.device.image, template, TRAINING_HEADER_AREA) > 0.9

    def _open_training(self):
        self.device.screenshot()
        if self._training_visible():
            return
        self.ui_ensure(page_dorm)
        if rgb_template(ASSETS / 'roster_close.png') is None:
            raise RequestHumanTakeover('Dorm roster close asset missing')

        def roster_visible():
            return locate_roster_close(self.device.image) is not None

        for _ in range(3):
            if roster_visible():
                break
            if not self.ui_page_appear(page_dorm):
                raise RequestHumanTakeover('Unexpected page before opening dorm roster')
            self.device.sleep(1)
            self.device.click(point_button(105, 675, 'DORM_TRAINING_ENTER'))
            try:
                self._wait(roster_visible, 'dorm roster popup')
                break
            except RequestHumanTakeover:
                if not self.ui_page_appear(page_dorm):
                    raise
        else:
            raise RequestHumanTakeover('Dorm roster entry repeatedly ignored')
        # Training is always the first-floor tab, even when the room view is 2F.
        if not self._training_visible():
            self.device.sleep(0.8)
            self.device.click(point_button(250, 111, 'DORM_TRAINING_TAB'))
        self._wait(self._training_visible, 'first-floor training roster')

    def _close_training(self):
        if not self._training_visible():
            raise RequestHumanTakeover('Cannot close an unknown dorm panel')
        # A single tap is dropped by the game now and then, and a roster left open
        # blocks page identification for every task, so retry before giving up.
        for attempt in range(3):
            button = locate_roster_close(self.device.image)
            if button is None:
                button = ROSTER_CLOSE_FALLBACK
            self.device.click(button)
            try:
                self._wait(lambda: self.ui_page_appear(page_dorm), 'dorm room')
                return
            except RequestHumanTakeover:
                if not self._training_visible():
                    raise
                logger.info(f'Dorm training close was ignored, retrying ({attempt + 1}/3)')
        raise RequestHumanTakeover('Dorm training roster did not close after 3 taps')

    @staticmethod
    def _slot_button(slot):
        return point_button(round(220 + (slot - 1) * 170), 335, 'DORM_TRAINING_SLOT_' + str(slot))

    def _counts(self):
        previous = None
        for _ in range(4):
            self.device.screenshot()
            current, _, capacity = DORM_COUNT.ocr(self.device.image)
            if 1 <= capacity <= 6 and 0 <= current <= capacity:
                if previous == (current, capacity):
                    return current, capacity
                previous = (current, capacity)
        raise RequestHumanTakeover('Dorm occupied/unlocked slot count is uncertain')

    def _detail_from_slot(self, slot):
        for _ in range(3):
            if not self._training_visible():
                raise RequestHumanTakeover('Refusing detail input outside training roster')
            self.device.long_click(self._slot_button(slot), duration=(1.6, 1.8))
            try:
                self._wait(lambda: self.appear(EQUIPMENT_OPEN, offset=(5, 5)) or
                           self.appear(DOCK_CHECK, offset=(20, 20)), 'ship details')
            except RequestHumanTakeover:
                if self._training_visible():
                    logger.info('Dorm long press was ignored, retrying the verified slot')
                    continue
                raise
            if self.appear(EQUIPMENT_OPEN, offset=(5, 5)):
                return self.read_ship()
            # A long press can be interpreted as a normal selection click.
            self._cancel_selection()
        raise RequestHumanTakeover('Dorm long press repeatedly opened selection')

    def inspect_roster(self):
        self._open_training()
        current, capacity = self._counts()
        levels = LevelOcr([(round(142+i*170)+80, 208, round(142+i*170)+153, 238)
                           for i in range(capacity)], name='DormRosterLevels').ocr(self.device.image)
        if not isinstance(levels, list):
            levels = [levels]
        occupied = [i+1 for i, level in enumerate(levels) if 1 <= level <= 125]
        if len(occupied) != current:
            raise RequestHumanTakeover('Dorm card levels disagree with occupied slot count')
        ships = {slot: None for slot in range(1, capacity+1)}
        for slot in occupied:
            ships[slot] = self._detail_from_slot(slot)
            self.device.click(BACK_ARROW)
            self._wait(self._training_visible, 'return from ship details')
        names = [ship.name for ship in ships.values() if ship]
        if len(names) != len(set(names)):
            raise RequestHumanTakeover('Duplicate or unstable dorm identities')
        return ships, capacity

    def _open_selection(self, slot):
        for _ in range(3):
            if not self._training_visible():
                raise RequestHumanTakeover('Refusing selection outside first-floor roster')
            self.device.sleep(0.8)
            self.device.click(self._slot_button(slot))
            try:
                self._wait(lambda: self.appear(DOCK_CHECK, offset=(20, 20)), 'dorm selection')
                break
            except RequestHumanTakeover:
                if not self._training_visible():
                    raise
        else:
            raise RequestHumanTakeover('Dorm selection click repeatedly ignored')
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set(True)
        self.dock_filter_set(index='ss', faction='all')
        DORM_SCROLL.set_top(main=self)

    def _cancel_selection(self):
        if not self.appear(DOCK_CHECK, offset=(20, 20)):
            raise RequestHumanTakeover('Cannot cancel unknown dorm selection')
        self.device.click(point_button(806, 670, 'DORM_SELECTION_CANCEL'))
        self._wait(self._training_visible, 'cancel dorm selection')

    def _scan_selection(self, target=None):
        names, previous = set(), None
        for _ in range(40):
            self.device.screenshot()
            cards = dock_cards(self.device.image)
            if not cards:
                raise RequestHumanTakeover('Dorm selection cards are not identifiable')
            texts = Ocr([(b.area[0], b.area[1]+164, b.area[2], b.area[1]+189) for b in cards],
                        lang='cnocr', name='DormSelectionNames').ocr(self.device.image)
            visible = [catalog_name(t) for t in texts]
            narrow = Ocr([(b.area[0], b.area[1]+166, b.area[2], b.area[1]+184) for b in cards],
                         lang='cnocr', name='DormSelectionNamesNarrow').ocr(self.device.image)
            for index, text in enumerate(narrow):
                name = catalog_name(text)
                if visible[index] is None:
                    visible[index] = name
                elif name is not None and name != visible[index]:
                    visible[index] = None
            # cnocr reads the current U-2501 card as U-2591; corroborate its
            # captured label instead of mapping a potentially different name.
            template = cv2.imread(str(ASSETS / 'u2501_dock_name.png'), 0)
            if template is None:
                raise RequestHumanTakeover('U-2501 dock label asset missing')
            for index, card in enumerate(cards):
                if visible[index] is None:
                    x, y, x2, _ = card.area
                    region = cv2.cvtColor(self.device.image[y+164:y+189, x:x2], cv2.COLOR_RGB2GRAY)
                    if cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max() > 0.92:
                        visible[index] = 'U-2501'
            levels = LevelOcr([(b.area[0]+77, b.area[1]+5, b.area[2], b.area[1]+27)
                               for b in cards], name='DormSelectionLevels').ocr(self.device.image) if target else [None]*len(cards)
            if target and any(not 1 <= level <= 125 for level in levels):
                alternate = LevelOcr([(b.area[0]+76, b.area[1]+4, b.area[2], b.area[1]+28)
                                      for b in cards], name='DormSelectionLevelsAlternate').ocr(self.device.image)
                levels = [old if 1 <= old <= 125 else new for old, new in zip(levels, alternate)]
            fresh = {n for n in visible if n} - names
            if fresh:
                self.device.click_record_clear()
            for card, name, level in zip(cards, visible, levels):
                if name:
                    names.add(name)
                if target and name == target.name and level == target.level:
                    return card
            if DORM_SCROLL.at_bottom(main=self) or (previous == tuple(visible) and any(visible)):
                break
            previous = tuple(visible)
            DORM_SCROLL.next_page(main=self, page=0.45)
            self.device.sleep(0.5)
        if target:
            raise RequestHumanTakeover('Submarine not available in dorm selection: ' + target.name)
        return names

    def _toggle(self, ship, delta, capacity):
        DORM_SCROLL.set_top(main=self)
        card = self._scan_selection(ship)
        before, _, total = OCR_DOCK_SELECTED.ocr(self.device.image)
        if total != capacity or not 0 <= before + delta <= capacity:
            raise RequestHumanTakeover('Unexpected dorm selection count before toggle')
        # Opening details from this multi-select dock discards its draft.
        # Details were read in the regular dock; corroborate the card itself here.
        if delta > 0 and not ship.is_rainbow:
            x, y, x2, _ = card.area
            pixels = self.device.image[y+178:y+207, x+10:x2-10].astype('int16')
            red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
            gold = ((red > 170) & (green > 145) & (blue < 180) &
                    (red-blue > 50) & (green-blue > 40)).astype('uint8')
            _, _, components, _ = cv2.connectedComponentsWithStats(gold)
            stars = sum(9 <= w <= 16 and 9 <= h <= 15 and 45 <= area <= 120
                        for _, _, w, h, area in components[1:])
            from module.os.training_ui import CATALOG
            maximum = CATALOG[ship.name]['max_stars']
            logger.info(f'Dorm card stars {ship.name}: {stars}/{maximum}')
            if not 1 <= stars <= maximum or (stars == maximum) != ship.fully_limit_broken:
                raise RequestHumanTakeover('Dorm card limit break differs from inspected ship: ' + ship.name)
        def toggled():
            current, _, limit = OCR_DOCK_SELECTED.ocr(self.device.image)
            return limit == capacity and current == before + delta
        x, y, x2, y2 = card.area
        for _ in range(3):
            self.device.click(point_button((x+x2)//2, (y+y2)//2, 'DORM_TOGGLE_' + ship.name))
            try:
                self._wait(toggled, 'toggle ' + ship.name)
                return
            except RequestHumanTakeover:
                if not self.appear(DOCK_CHECK, offset=(20, 20)) or OCR_DOCK_SELECTED.ocr(self.device.image) != (before, capacity-before, capacity):
                    raise
        raise RequestHumanTakeover('Dorm card toggle repeatedly ignored: ' + ship.name)

    def _draft(self, current, planned, capacity):
        changed = [s for s in planned if current[s] is None or current[s].name != planned[s].name]
        slot = changed[0]
        self._open_selection(slot)
        count, _, limit = OCR_DOCK_SELECTED.ocr(self.device.image)
        expected = sum(s is not None for s in current.values()) - (current[slot] is not None)
        if count != expected or limit != capacity:
            raise RequestHumanTakeover('Opening a dorm slot did not deselect the expected ship')
        for s in changed:
            if s != slot and current[s] is not None:
                self._toggle(current[s], -1, capacity)
        for s in changed:
            self._toggle(planned[s], 1, capacity)
        count, _, limit = OCR_DOCK_SELECTED.ocr(self.device.image)
        if count != capacity or limit != capacity:
            raise RequestHumanTakeover('Dorm selection is incomplete; nothing confirmed')

    def maintain(self, now=None):
        now = now or datetime.now().replace(microsecond=0)
        self.device.screenshot()
        self._check_cn()
        current, capacity = self.inspect_roster()
        plan = plan_dorm_rotation(current, [], capacity)
        if not plan.success:
            replace_slot = next(s for s, ship in current.items() if ship is None or
                                (ship.position == 'submarine' and not decide_trainability(ship).allowed))
            self._open_selection(replace_slot)
            try:
                available = self._scan_selection()
            finally:
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    self._cancel_selection()
            self._close_training()
            needed = sum(ship is None or (ship.position == 'submarine' and not decide_trainability(ship).allowed)
                         for ship in current.values())
            candidates = self.find_candidates('submarine', frozenset(),
                                              {s.name for s in current.values() if s},
                                              needed=needed, available=available, scroll=DORM_SCROLL)
            plan = plan_dorm_rotation(current, candidates, capacity)
        if not plan.success:
            raise RequestHumanTakeover('No complete dorm submarine plan: ' + plan.reason)
        logger.info('Dorm training plan: ' + ', '.join(f'{s}={ship.name}' for s, ship in sorted(plan.slots.items())))
        # Awaken in the regular dock, verifying identity again immediately before spending.
        for slot, ship in list(plan.slots.items()):
            if not should_awaken_in_dorm(ship):
                continue
            from module.ui.page import page_dock
            if self._training_visible():
                self._close_training()
            self.ui_ensure(page_dock)
            self.dock_favourite_set(False)
            self.dock_filter_set(index='ss', faction='all')
            DORM_SCROLL.set_top(main=self)
            card = self._scan_selection(ship)
            self.ship_info_enter(card, long_click=False)
            actual = self.read_ship()
            if actual.name != ship.name or not decide_trainability(actual).allowed:
                raise RequestHumanTakeover('Dorm awakening identity or eligibility changed')
            for _ in range(4):
                if not should_awaken_in_dorm(actual):
                    break
                if self.awaken_once(use_array=False) != 'success':
                    raise RequestHumanTakeover('Dorm awakening could not complete: ' + actual.name)
                awakened = self.read_ship()
                if any(getattr(awakened, key) != getattr(actual, key) for key in
                       ('name', 'faction', 'position', 'is_rainbow', 'fully_limit_broken')):
                    raise RequestHumanTakeover('Dorm ship identity changed after awakening')
                actual = awakened
            if should_awaken_in_dorm(actual):
                raise RequestHumanTakeover('Dorm awakening did not settle')
            plan.slots[slot] = actual
            self.device.click(BACK_ARROW)
            self._wait(lambda: self.appear(DOCK_CHECK, offset=(20, 20)), 'return from dorm awakening')
        self._open_training()
        if any(current[s] is None or current[s].name != plan.slots[s].name for s in current):
            try:
                self._draft(current, plan.slots, capacity)
                self.device.click(point_button(1020, 671, 'DORM_SELECTION_CONFIRM'))
                self._wait(self._training_visible, 'confirmed first-floor roster')
            except Exception:
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    self._cancel_selection()
                raise
            actual, actual_capacity = self.inspect_roster()
            if actual_capacity != capacity or {s.name for s in actual.values() if s} != {s.name for s in plan.slots.values()}:
                raise RequestHumanTakeover('Confirmed dorm roster differs from plan')
        self._close_training()
        self.config.DormTraining_LastCheck = now
        logger.info('Dorm submarine maintenance verified')


def maintain_dorm_if_due(config, device):
    if not getattr(config, 'DormTraining_Enable', False):
        return
    last = getattr(config, 'DormTraining_LastCheck', datetime(2020, 1, 1))
    if isinstance(last, datetime) and last.date() == datetime.now().date():
        return
    DormTraining(config, device).maintain()
