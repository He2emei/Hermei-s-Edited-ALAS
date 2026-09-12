"""CN event hard-fleet preparation, grounded in the 2026-09 fleet/dock UI."""
import re
from collections import Counter
import cv2

from module.combat.level import LevelOcr
from module.awaken.assets import OCR_SHIP_LEVEL
from module.equipment.assets import EQUIPMENT_OPEN
from module.event.fleet_source import EventFleetNameOcr, normalize_ship_name
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.map.assets import FLEET_PREPARATION
from module.ocr.ocr import Ocr, Digit
from module.os.training_ui import CATALOG, point_button
from module.retire.assets import DOCK_CHECK, SHIP_CONFIRM
from module.retire.card_geometry import dock_cards
from module.retire.dock import Dock, DOCK_SCROLL, OCR_DOCK_SELECTED
from module.ui.assets import BACK_ARROW


EVENT_TASKS = {'Event', 'Event2', 'EventC', 'EventD', 'EventSp'}
SLOT_X = (391, 494, 597, 707, 810, 911)
SLOT_Y = (178, 292)
KNOWN_SHIP_NAMES = {normalize_ship_name(name) for name in CATALOG}


def event_fleet_stage(config):
    if not getattr(config, 'EventFleet_AutoPrepare', False) \
            or config.Scheduler_Command not in EVENT_TASKS \
            or not str(config.Campaign_Event).startswith('event_'):
        return None
    stage = str(config.Campaign_Name).lower()
    return stage if re.fullmatch(r'[cd][1-3]|sp', stage) else None


def c_roster_matches(current, source):
    """The auxiliary fleet is exactly one main ship and one Downes/Cassin."""
    if len(current) != 12 or len(source) != 6:
        return False
    mains = [ship for ship in current[:3] if ship]
    fronts = [ship for ship in current[3:6] if ship]
    if len(mains) != 1 or len(fronts) != 1 or not is_auxiliary_destroyer(fronts[0]['name']):
        return False
    return all(actual and actual['name'] == wanted['name'] and actual['level'] == wanted['level']
               for actual, wanted in zip(current[6:], source))


def is_auxiliary_destroyer(name):
    return re.sub(r'[.·]?改$', '', normalize_ship_name(name)) in {'唐斯', '卡辛'}


class EventFleetPreparation(Dock):
    def __init__(self, main):
        super().__init__(main.config, main.device)
        self.main = main

    def _wait(self, predicate, description, attempts=35):
        for _ in range(attempts):
            self.device.screenshot()
            if predicate():
                return
            self.device.sleep(0.2)
        raise RequestHumanTakeover('Event fleet: timed out waiting for ' + description)

    def _at_preparation(self):
        return self.appear(FLEET_PREPARATION, offset=(20, 50))

    @staticmethod
    def _slot(index):
        return point_button(SLOT_X[index % 6] + 40, SLOT_Y[index // 6] + 40,
                            f'EVENT_FLEET_SLOT_{index + 1}')

    def levels(self):
        areas = [(x + 20, y, x + 80, y + 23) for y in SLOT_Y for x in SLOT_X]
        return LevelOcr(areas, name='EventPreparedLevels').ocr(self.device.image)

    def empty_slots(self):
        template = cv2.imread('./assets/cn/event_fleet/empty_slot.png', 0)
        if template is None:
            raise RequestHumanTakeover('Event empty-slot template is missing')
        gray = cv2.cvtColor(self.device.image, cv2.COLOR_RGB2GRAY)
        return [cv2.matchTemplate(gray[y:y + 80, x:x + 80], template,
                                  cv2.TM_CCOEFF_NORMED).max() > 0.9
                for y in SLOT_Y for x in SLOT_X]

    def _stable_levels(self):
        previous = None
        for _ in range(35):
            self.device.screenshot()
            levels = self.levels()
            empty = self.empty_slots()
            valid = len(levels) == 12 and all((1 <= v <= 125 and not blank) or (v == 0 and blank)
                                             for v, blank in zip(levels, empty))
            if valid and levels == previous:
                return levels
            previous = levels if valid else None
            self.device.sleep(0.2)
        raise RequestHumanTakeover('Event fleet levels are unstable')

    def _read_slot(self, index):
        if not self._at_preparation():
            raise RequestHumanTakeover('Refusing ship inspection outside fleet preparation')
        for attempt in range(3):
            self.device.sleep(0.35)
            self.device.long_click(self._slot(index), duration=(1.5, 1.7))
            try:
                self._wait(lambda: self.appear(EQUIPMENT_OPEN, offset=(5, 5)), 'ship details', attempts=12)
                break
            except RequestHumanTakeover:
                if attempt == 2 or not self._at_preparation():
                    raise
        previous = None
        result = None
        for _ in range(8):
            self.device.screenshot()
            areas = [(210, 88, 425, 120), (210, 90, 425, 115), (210, 89, 425, 114)]
            texts = Ocr(areas, lang='cnocr', name='EventPreparedName').ocr(self.device.image)
            texts += EventFleetNameOcr(areas, lang='cnocr', name='EventPreparedNameColor').ocr(self.device.image)
            votes = Counter(normalize_ship_name(t) for t in texts if normalize_ship_name(t))
            # Prefer complete exact catalog spellings over decorative OCR such
            # as "一卡辛". Unknown/custom names still require a unique vote.
            known = Counter({name: count for name, count in votes.items() if name in KNOWN_SHIP_NAMES})
            ranked = (known or votes).most_common()
            name = ranked[0][0] if ranked and ranked[0][1] >= 2 \
                and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]) else ''
            level = Digit(OCR_SHIP_LEVEL, letter=(255, 255, 255), threshold=128,
                          name='EventPreparedLevel').ocr(self.device.image)
            current = {'name': name, 'level': level}
            if name and 1 <= level <= 125 and current == previous:
                result = current
                break
            previous = current
        self.device.click(BACK_ARROW)
        self._wait(self._at_preparation, 'return from ship details')
        if result is None:
            raise RequestHumanTakeover('Event fleet ship detail is unreadable')
        return result

    def read_roster(self):
        levels = self._stable_levels()
        return [self._read_slot(i) if value else None for i, value in enumerate(levels)]

    def _find_ship(self, target, *, auxiliary=False, excluded=()):
        self.dock_favourite_set(False)
        self.dock_filter_set(index='dd' if auxiliary else ('bb' if target is None else 'all'),
                             faction='eagle' if auxiliary else 'all')
        self.dock_sort_method_dsc_set(True)
        DOCK_SCROLL.set_top(main=self)
        previous = None
        for page in range(80):
            self.device.screenshot()
            cards = dock_cards(self.device.image)
            if not cards:
                raise RequestHumanTakeover('Event fleet dock card geometry is unreadable')
            votes = [Counter() for _ in cards]
            for top in (167, 168, 169):
                areas = [(b.area[0] + 15, b.area[1] + top, b.area[2] - 15, b.area[1] + top + 19) for b in cards]
                for cls in (Ocr, EventFleetNameOcr):
                    names = cls(areas, lang='cnocr', name='EventDockNames').ocr(self.device.image)
                    for vote, name in zip(votes, names):
                        vote[normalize_ship_name(name)] += 1
            levels = LevelOcr([(b.area[0] + 77, b.area[1] + 5, b.area[2], b.area[1] + 27)
                               for b in cards], name='EventDockLevels').ocr(self.device.image)
            names = []
            for vote in votes:
                if target:
                    name = target['name'] if target['name'] in vote else ''
                elif auxiliary:
                    matches = [n for n in vote if is_auxiliary_destroyer(n)]
                    name = matches[0] if len(matches) == 1 else ''
                else:
                    matches = [n for n in vote if n in KNOWN_SHIP_NAMES and n not in excluded]
                    name = matches[0] if len(matches) == 1 else ''
                names.append(name)
            candidates = []
            for card, name, level in zip(cards, names, levels):
                if not name or name in excluded or not 1 <= level <= 125:
                    continue
                if target and (name != target['name'] or level != target['level']):
                    continue
                if auxiliary and not is_auxiliary_destroyer(name):
                    continue
                candidates.append((card, {'name': name, 'level': level}))
            if candidates:
                if target and len(candidates) != 1:
                    raise RequestHumanTakeover('Ambiguous duplicate event ship: ' + target['name'])
                return candidates[0]
            signature = tuple((tuple(sorted(vote)), level) for vote, level in zip(votes, levels))
            if DOCK_SCROLL.at_bottom(main=self) or signature == previous:
                break
            previous = signature
            self.device.click_record_clear()
            # The dock's minimum thumb height overstates a page in large docks.
            # Drag one card row in the content so no unseen row is skipped.
            self.device.drag((1068, 560), (1068, 335), point_random=(0, 0, 0, 0),
                             hold_duration=0.2, name='EVENT_DOCK_NEXT_ROW')
            self.device.sleep(0.5)
        raise RequestHumanTakeover('Event fleet candidate not found: ' +
                                   (target['name'] if target else 'Downes/Cassin' if auxiliary else 'main ship'))

    def _fill_slot(self, index, target=None, *, auxiliary=False, excluded=(), read_index=None):
        if not self._at_preparation():
            raise RequestHumanTakeover('Refusing ship selection outside fleet preparation')
        for attempt in range(3):
            self.device.sleep(0.5)
            self.device.click(self._slot(index))
            try:
                self._wait(lambda: self.appear(DOCK_CHECK, offset=(20, 20)), 'ship selection', attempts=12)
                break
            except RequestHumanTakeover:
                if attempt == 2 or not self._at_preparation():
                    raise
        card, chosen = self._find_ship(target, auxiliary=auxiliary, excluded=excluded)
        self.device.click(card)
        self._wait(lambda: OCR_DOCK_SELECTED.ocr(self.device.image)[0] == 1, 'one selected ship')
        # Event selection places Confirm left of the ordinary dock's button.
        self.device.click(point_button(1015, 670, 'EVENT_DOCK_CONFIRM'))
        self._wait(self._at_preparation, 'confirmed ship selection')
        actual = self._read_slot(index if read_index is None else read_index)
        if actual != chosen:
            raise RequestHumanTakeover(f'Event fleet selection differs: wanted {chosen}, got {actual}')
        return actual

    def _recommend(self, fleet):
        if not self._at_preparation() or not fleet.is_hard():
            raise RequestHumanTakeover('Event recommendation button is unavailable')
        self.device.click(fleet._advice)
        self.device.sleep(0.7)
        for _ in range(20):
            self.device.screenshot()
            if self.handle_popup_confirm('EVENT_FLEET_RECOMMEND'):
                continue
            if self._at_preparation():
                return
        raise RequestHumanTakeover('Event recommendation did not return to preparation')

    def _clear_fleet(self, fleet, row):
        # The old in_use() crop includes the colored hull requirement badge on
        # empty C slots, so it can keep clicking Clear after all ships are gone.
        if not any(self._stable_levels()[row * 6:row * 6 + 6]):
            return
        self.device.click(fleet._clear)
        empty_frames = 0
        for _ in range(35):
            self.device.sleep(0.2)
            self.device.screenshot()
            if self.handle_popup_confirm('EVENT_FLEET_CLEAR'):
                continue
            if not self._at_preparation():
                continue
            empty_frames = empty_frames + 1 if all(self.empty_slots()[row * 6:row * 6 + 6]) else 0
            if empty_frames >= 2:
                return
        raise RequestHumanTakeover('Event fleet clear was not confirmed')

    def run(self, fleet_1, fleet_2, submarine=None):
        stage = event_fleet_stage(self.config)
        if stage is None:
            return False
        if self.config.SERVER != 'cn' or self.device.image.shape[:2] != (720, 1280):
            raise RequestHumanTakeover('Event automatic fleet preparation supports CN 1280x720 only')
        if not fleet_1.is_hard() or not fleet_2.is_hard():
            raise RequestHumanTakeover('Event fleet preparation has no two hard-fleet recommendation buttons')
        if stage.startswith('c'):
            source = getattr(self.config, '_event_source_roster', None)
            if not source or len(source) != 6 or len({s['name'] for s in source}) != 6:
                raise RequestHumanTakeover('Event C requires six distinct verified source ships')
            current = self.read_roster()
            if not c_roster_matches(current, source):
                excluded = {s['name'] for s in source}
                mains = [s for s in current[:3] if s]
                fronts = [s for s in current[3:6] if s]
                if len(mains) > 1 or len(fronts) > 1 or (fronts and not is_auxiliary_destroyer(fronts[0]['name'])) \
                        or any(s['name'] in excluded for s in mains + fronts):
                    # Release any source ship from fleet 1 before filling fleet 2.
                    self._clear_fleet(fleet_1, 0)
                    mains, fronts = [], []
                # Resume an interrupted fill without disturbing verified ships.
                # A differing occupied source slot requires rebuilding fleet 2.
                if any(actual and (actual['name'], actual['level']) != (wanted['name'], wanted['level'])
                       for actual, wanted in zip(current[6:], source)):
                    self._clear_fleet(fleet_2, 1)
                    current[6:] = [None] * 6
                for index, ship in enumerate(source, 6):
                    if current[index] is None:
                        self._fill_slot(index, ship)
                if not mains:
                    self._fill_slot(0, excluded=excluded)
                # The first empty C vanguard slot can be restricted to cruisers.
                # Use the unrestricted last slot; the game packs the single DD
                # into the first occupied vanguard position after confirmation.
                if not fronts:
                    self._fill_slot(5, auxiliary=True, excluded=excluded, read_index=3)
                if not c_roster_matches(self.read_roster(), source):
                    raise RequestHumanTakeover('Event C final roster does not match the plan')
            logger.info('Event C fleet verified: one main + Downes/Cassin; fleet 2 matches normal source')
        else:
            levels = self._stable_levels()
            for index, fleet in enumerate((fleet_1, fleet_2)):
                if not all(levels[index * 6:index * 6 + 6]) or not fleet.is_hard_satisfied():
                    self._recommend(fleet)
            if not all(self._stable_levels()):
                raise RequestHumanTakeover('Event recommended fleets do not fill all 12 positions')
            logger.info(f'Event {stage.upper()} recommended fleet verified: 12 occupied positions')
        fleet_1.raise_hard_not_satisfied()
        fleet_2.raise_hard_not_satisfied()
        # SP has its own submarine roster. Honor the profile's existing request
        # for submarine support, including when that event roster starts empty.
        if submarine is not None and self.config.Submarine_Fleet and submarine.allow() \
                and submarine.is_hard_satisfied() is False:
            self._recommend(submarine)
            submarine.raise_hard_not_satisfied()
        return True
