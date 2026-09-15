"""Verified CN coin panel, independent of a ship's changing bottom-row index."""
import re

import cv2

from module.exception import RequestHumanTakeover
from module.ocr.ocr import Ocr
from module.os.training_ui import catalog_name, point_button
from module.shipyard.auto_policy import parse_required_level
from module.shipyard.ui import ShipyardUI
from module.shipyard.assets import (SHIPYARD_IN_FATE,
                                   SHIPYARD_PROGRESS_DEV, SHIPYARD_PROGRESS_FATE)


def panel_text(image, fate=False):
    area = (1020, 412, 1100, 440) if fate else (1043, 388, 1125, 416)
    return Ocr(area, lang='cnocr', name='ShipyardResource').ocr(image).replace(' ', '')


def panel_coins(image, fate=False):
    area = (1110, 412, 1260, 440) if fate else (1130, 388, 1273, 416)
    text = Ocr(area, lang='cnocr', name='ShipyardCoinStock').ocr(image).replace(' ', '')
    match = re.fullmatch(r'库存[:：](\d{1,7})', text)
    if not match:
        raise RequestHumanTakeover('Unknown shipyard coin inventory: ' + text)
    return int(match[1])


def panel_cost(image, fate=False):
    # The icon corner shows the NEXT unit price, not this selection's sum.
    # The gray number on the separate "消耗物资" line is the total.
    area = (1192, 494, 1241, 516) if fate else (1136, 470, 1173, 492)
    text = Ocr(area, alphabet='0123456789ID', letter=(190, 190, 190),
               threshold=128, name='ShipyardCoinCost').ocr(image)
    text = text.replace('I', '1').replace('D', '0')
    if re.fullmatch(r'\d{1,5}', text):
        return int(text)
    raise RequestHumanTakeover('Unknown shipyard coin cost: ' + text)


def panel_next_cost(image, fate=False):
    """Valid ONLY with zero selected: the icon then shows the next unit price."""
    area = (959, 472, 1001, 488) if fate else (989, 448, 1031, 464)
    text = Ocr(area, alphabet='0123456789ID', threshold=64, name='ShipyardNextPrice').ocr(image)
    text = text.replace('I', '1').replace('D', '0')
    if re.fullmatch(r'[1-9]\d{0,3}', text):
        return int(text)
    template = cv2.imread('./assets/cn/shipyard_auto/free_coin_fate.png' if fate
                          else './assets/cn/shipyard_auto/free_coin.png')
    template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
    area = image[437:471, 936:1004] if fate else image[413:447, 966:1034]
    if cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED).max() > 0.93:
        return 0
    raise RequestHumanTakeover('Unknown next shipyard unit price: ' + text)


def required_level(image, fate=False):
    area = (1015, 175, 1190, 199) if fate else (1110, 149, 1278, 175)
    return parse_required_level(Ocr(area, lang='cnocr', letter=(200, 50, 20) if fate else (255, 255, 255),
                                    name='ShipyardLevelGate').ocr(image))


class AutoShipyardUI(ShipyardUI):
    def auto_fate(self):
        return self.appear(SHIPYARD_IN_FATE, offset=(20, 20))

    def auto_name(self):
        # Read in DEV before entering Fate; both pages have different name ROIs.
        if self.auto_fate():
            self.device.click(point_button(1001, 539, 'SHIPYARD_FATE_BACK'))
            self.device.sleep(1.5)
            self.device.screenshot()
        texts = Ocr([(610, 100, 775, 123), (610, 98, 775, 125)],
                    lang='cnocr', name='ShipyardIdentity').ocr(self.device.image)
        names = {catalog_name(t) for t in texts} - {None}
        return next(iter(names)) if len(names) == 1 else None

    def auto_enter(self):
        if not self._shipyard_buy_enter():
            return False
        self.device.sleep(1.5)
        self.device.screenshot()
        return True

    def auto_full(self):
        return self.appear(SHIPYARD_PROGRESS_FATE if self.auto_fate() else SHIPYARD_PROGRESS_DEV,
                           offset=(20, 20))

    def auto_set_amount(self, target):
        if not 0 <= target <= 3000:
            raise RequestHumanTakeover('Invalid shipyard selection target')
        for _ in range(320):
            plus, minus, before = self._shipyard_get_total()
            if before == target:
                return before
            n = min(10, abs(target - before))
            self.device.multi_click(plus if target > before else minus, n=n, interval=(0.12, 0.15))
            self.device.sleep(0.3)
            self.device.screenshot()
            _, _, after = self._shipyard_get_total()
            if after == before:
                return after
            if not min(before, target) <= after <= max(before, target):
                raise RequestHumanTakeover('Unexpected shipyard quantity change')
            self.device.click_record_clear()  # verified bounded selector progress
        raise RequestHumanTakeover('Shipyard quantity selection timed out')

    def auto_observe(self):
        previous = None
        for _ in range(4):
            self.device.screenshot()
            fate = self.auto_fate()
            if panel_text(self.device.image, fate) != '物资':
                raise RequestHumanTakeover('Coin catch-up panel is not active')
            _, _, amount = self._shipyard_get_total()
            reading = (amount, panel_cost(self.device.image, fate) if amount else 0,
                       panel_coins(self.device.image, fate))
            if reading == previous:
                return reading
            previous = reading
        raise RequestHumanTakeover('Shipyard price preview is unstable')
