"""[heremei] Screenshot-verified CN ship inspection for OpSi fleet training."""
import json
import re
from pathlib import Path

import cv2

from module.awaken.awaken import Awaken
from module.awaken.assets import OCR_SHIP_LEVEL
from module.base.button import Button, ButtonGrid
from module.base.utils import crop
from module.combat.level import LevelOcr
from module.equipment.assets import EQUIPMENT_OPEN
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Digit, Ocr
from module.os.training_policy import ShipCandidate, decide_trainability, should_awaken
from module.retire.card_geometry import dock_cards
from module.retire.dock import DOCK_SCROLL
from module.retire.assets import DOCK_CHECK
from module.ui.assets import BACK_ARROW
from module.ui.page import page_dock

CATALOG = json.loads(Path(__file__).with_name('ship_training_catalog.json').read_text(encoding='utf-8'))['ships']
for _name, _data in json.loads(Path(__file__).with_name('ship_training_overrides.json').read_text(encoding='utf-8'))['ships'].items():
    CATALOG.setdefault(_name, _data)
FACTIONS = {1: '白鹰', 2: '皇家', 3: '重樱', 4: '铁血', 5: '东煌', 6: '撒丁帝国',
            7: '北联', 8: '自由鸢尾', 9: '维希教廷', 10: '郁金王国', 11: '晶石联盟',
            96: '飓风', 97: 'META'}
FILTER_FACTIONS = {'白鹰': 'eagle', '皇家': 'royal', '重樱': 'sakura', '铁血': 'iron',
                   '东煌': 'dragon', '撒丁帝国': 'sardegna', '北联': 'northern',
                   '自由鸢尾': 'iris', '维希教廷': 'vichya', 'META': 'meta',
                   '郁金王国': 'tulipa', '晶石联盟': 'pedreria', '飓风': 'tempesta'}
MAP_SHIPS = ButtonGrid((20, 133), (0, 100), (65, 65), (1, 6), name='TRAINING_MAP_SHIP')


def point_button(x, y, name):
    return Button((x - 3, y - 3, x + 3, y + 3), (0, 0, 0),
                  (x - 3, y - 3, x + 3, y + 3), name=name)




def normalise_name(name):
    return re.sub(r'\s+', '', name).strip('_- .、，〉》〈《><')


def catalog_name(text):
    name = normalise_name(text)
    # Exact cnocr substitution verified against the 2026-09-08 detail screenshot.
    name = {'朝咀': '朝凪'}.get(name, name)
    # This combined character's name scrolls beyond the detail label width.
    # The distinctive exact prefix is verified in current-slot6.png.
    if '八舞耶俱矢八舞' in name.replace('·', ''):
        name = '八舞耶俱矢·八舞夕弦'
    if name in CATALOG:
        return name
    # Cosmetic punctuation variation only; never fuzzy-match identities.
    key = lambda n: re.sub(r'[·.;；:：]', '', normalise_name(n))
    matches = [n for n in CATALOG if key(n) == key(name)]
    return matches[0] if len(matches) == 1 else None


class TrainingShipInspector(Awaken):
    def _check_cn(self):
        if self.config.SERVER != 'cn' or self.device.image.shape[:2] != (720, 1280):
            raise RequestHumanTakeover('Training fleet requires verified CN 1280x720 UI')

    def read_ship(self):
        """Read a detail page twice, rejecting unknown identities and counters."""
        self._check_cn()
        previous = None
        star = cv2.imread('./assets/cn/opsi_training/gold_star.png')
        if star is None:
            raise RequestHumanTakeover('Training star template missing')
        star = cv2.cvtColor(star, cv2.COLOR_BGR2RGB)
        for _ in range(4):
            self.device.screenshot()
            if not self.appear(EQUIPMENT_OPEN, offset=(5, 5)):
                continue
            texts = Ocr([(210, 88, 425, 120), (210, 90, 425, 115)], lang='cnocr', name='TrainingName').ocr(self.device.image)
            names = {catalog_name(t) for t in texts} - {None}
            name = next(iter(names)) if len(names) == 1 else None
            if name is None:
                # cnocr lacks a stable glyph for 凪. Use its exact captured
                # name label, never a fuzzy text substitution.
                template = cv2.imread('./assets/cn/opsi_training/asanagi.png', 0)
                region = cv2.cvtColor(self.device.image[88:120, 290:365], cv2.COLOR_RGB2GRAY)
                if template is not None and template.ndim == 2 and cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max() > 0.95:
                    name = '朝凪'
            level = Digit(OCR_SHIP_LEVEL, letter=(255, 255, 255), threshold=128, name='TrainingLevel').ocr(self.device.image)
            if name is None or not 1 <= level <= 125:
                continue
            data = CATALOG[name]
            faction = FACTIONS.get(data['faction'], '联动' if data['faction'] >= 100 else '')
            ship_type = data['type']
            side = 'main' if ship_type in (4, 5, 6, 7, 10, 12, 13, 21, 24) else 'vanguard' if ship_type in (1, 2, 3, 18, 19, 22, 23) else 'submarine' if ship_type in (8, 17) else ''
            if not side or not faction:
                continue
            values = cv2.matchTemplate(crop(self.device.image, (285, 57, 425, 90)), star, cv2.TM_CCOEFF_NORMED)
            stars = 0
            while float(values.max()) > 0.82:
                _, _, _, (x, _) = cv2.minMaxLoc(values)
                stars += 1
                values[:, max(0, x - 12):x + 13] = 0
            full = stars == data['max_stars']
            at_cap = False
            stored = None
            if level >= 100 and (full or data['rarity'] == 6):
                text = Ocr([(1080, 277, 1248, 308)], name='TrainingStoredExp').ocr(self.device.image)
                match = re.fullmatch(r'(\d{1,7})/[MmM8][Aa8][XxX]', text.replace(' ', ''))
                # The game font's lowercase "a" is regularly recognized as 8.
                if match and int(match.group(1)) <= 3_000_000:
                    at_cap = True
                    stored = int(match.group(1))
                elif not re.fullmatch(r'\d{1,7}/[1-9]\d{1,6}', text.replace(' ', '')):
                    continue
                elif level == 125:
                    continue
            cap = level if at_cap else 100 if level < 100 else min(125, (level // 5 + 1) * 5)
            ship = ShipCandidate(name, faction, side, level, data['rarity'] == 6, full, stored, cap)
            if ship == previous:
                logger.info(f'Training ship: {ship}')
                return ship
            previous = ship
        raise RequestHumanTakeover('Cannot reliably read ship identity, level, stars or stored XP')

    def awaken_for_training(self, ship):
        for _ in range(4):
            if not should_awaken(ship):
                return ship
            result = self.awaken_once(use_array=False)
            if result != 'success':
                raise RequestHumanTakeover(f'Training awakening stopped: {ship.name}: {result}')
            ship = self.read_ship()
        if should_awaken(ship):
            raise RequestHumanTakeover('Training awakening did not reach a stable cap')
        return ship

    def inspect_map_fleet(self, opsi):
        opsi.fleet_set(4)
        ships = {}
        for slot, button in enumerate(MAP_SHIPS.buttons, 1):
            opsi.ensure_no_map_event()
            self.ship_info_enter(button, long_click=True)
            ships[slot] = self.read_ship()
            self.device.click(BACK_ARROW)
            for _ in range(30):
                self.device.screenshot()
                if opsi.is_in_map():
                    break
            else:
                raise RequestHumanTakeover('Could not return from ship details to OpSi map')
        if ships[1].name != '英仙座' or ships[4].name != '伊吹':
            raise RequestHumanTakeover('Fourth fleet anchors differ from 英仙座 / 伊吹; no changes allowed')
        return ships

    def find_candidates(self, side, factions, excluded, needed=2, available=None, scroll=DOCK_SCROLL):
        """Inspect in dock order. Never select/remove a deployed ship here."""
        self.ui_ensure(page_dock)
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set(True)
        selected_factions = [FILTER_FACTIONS[f] for f in sorted(factions)] if factions else 'all'
        dock_side = 'ss' if side == 'submarine' else side
        self.dock_filter_set(index=dock_side, faction=selected_factions)
        scroll.set_top(main=self)
        found, seen = [], set(excluded)
        for _ in range(40):
            self.device.screenshot()
            cards = dock_cards(self.device.image)
            if not cards:
                raise RequestHumanTakeover('No stable dock card geometry')
            levels = LevelOcr([(b.area[0] + 77, b.area[1] + 5, b.area[2], b.area[1] + 27) for b in cards], name='TrainingDockLevels').ocr(self.device.image)
            names = Ocr([tuple((b.area[0], b.area[1] + 164, b.area[2], b.area[1] + 189))
                         for b in cards], lang='cnocr', name='TrainingDockNames').ocr(self.device.image)
            for button, level, raw_name in zip(cards, levels, names):
                name = catalog_name(raw_name)
                if not name or name in seen or not 1 <= level < 125 or (available is not None and name not in available):
                    continue
                seen.add(name)
                self.ship_info_enter(button, long_click=False)
                try:
                    ship = self.read_ship()
                except RequestHumanTakeover:
                    logger.warning(f'Training candidate skipped because details are unreadable: {name}')
                    self.device.click(BACK_ARROW)
                    self.wait_until_appear(DOCK_CHECK, offset=(20, 20))
                    continue
                if ship.name != name:
                    raise RequestHumanTakeover('Dock card and ship details disagree')
                decision = decide_trainability(ship)
                if decision.allowed and ship.position == side and (not factions or ship.faction in factions):
                    found.append(ship)
                else:
                    logger.info(f'Training skip {name}: {decision.reason}')
                self.device.click(BACK_ARROW)
                self.wait_until_appear(DOCK_CHECK, offset=(20, 20))
                if len(found) >= needed:
                    return found
            if scroll.at_bottom(main=self):
                break
            scroll.next_page(main=self, page=0.45)
            self.device.sleep(0.6)
        return found
