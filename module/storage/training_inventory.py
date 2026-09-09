"""Read CN training supplies without consuming, combining, or moving items."""
from pathlib import Path
import re

import cv2

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Ocr
from module.os.training_ui import point_button
from module.storage.ui import StorageUI
from module.ui.scroll import Scroll


ITEM_NAMES = {
    'destroyer': '驱逐改造图纸T3', 'cruiser': '巡洋改造图纸T3',
    'battleship': '战列改造图纸T3', 'carrier': '航母改造图纸T3',
    'exp_book_t1': '舰艇演习数据T1',
}
ASSET_ROOT = Path('./assets/cn/training_inventory')
INVENTORY_SCROLL = Scroll((1257, 94, 1264, 635), color=(247, 211, 66), name='TrainingInventoryScroll')


def item_position(image, key):
    """Find the exact item icon including its rarity background, excluding count."""
    template = cv2.imread(str(ASSET_ROOT / (key + '.png')))
    if template is None:
        raise RequestHumanTakeover('Training inventory icon missing: ' + key)
    template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
    scores = cv2.matchTemplate(image[55:637, 140:1240], template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.9:
        return None
    return x + 140 + template.shape[1] // 2, y + 55 + template.shape[0] // 2


def parse_owned_count(text, key):
    if not isinstance(text, str) or not re.fullmatch(r'\d{1,6}', text.strip()):
        return None
    count = int(text.strip())
    if count > (3000 if key == 'exp_book_t1' else 999999):
        return None
    return count


class TrainingInventory(StorageUI):
    def _wait(self, predicate, description):
        for _ in range(30):
            self.device.screenshot()
            if predicate():
                return
            self.device.sleep(0.2)
        raise RequestHumanTakeover('Training inventory timeout: ' + description)

    def _info_visible(self):
        template = cv2.imread(str(ASSET_ROOT / 'info_header.png'))
        if template is None:
            raise RequestHumanTakeover('Inventory information header asset missing')
        template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        return cv2.matchTemplate(self.device.image[170:228, 350:465], template,
                                 cv2.TM_CCOEFF_NORMED).max() > 0.9

    def _read_item(self, key, position):
        if not self._storage_in_material():
            raise RequestHumanTakeover('Inventory material page is not visible')
        self.device.click(point_button(*position, 'TRAINING_INVENTORY_' + key))
        self._wait(self._info_visible, 'item information')
        previous = None
        try:
            for _ in range(4):
                self.device.screenshot()
                title = Ocr([(530, 263, 920, 293)], lang='cnocr', letter=(255, 223, 82),
                            name='TrainingItemName').ocr(self.device.image)
                title = re.sub(r'\s+', '', title)
                # Exact T1 font substitution verified in the CN item dialog.
                title = re.sub(r'T[lI]$', 'T1', title)
                raw = Ocr([(450, 405, 522, 433)], letter=(239, 239, 0),
                          alphabet='0123456789', name='TrainingItemCount').ocr(self.device.image)
                count = parse_owned_count(raw, key)
                if title != ITEM_NAMES[key] or count is None:
                    previous = None
                    continue
                if previous == (title, count):
                    logger.info(f'Training inventory {key}: {count}')
                    return count
                previous = (title, count)
            raise RequestHumanTakeover(f'Unreliable inventory item details for {key}: {title}, {raw}')
        finally:
            if self._info_visible():
                self.device.click(point_button(895, 197, 'TRAINING_ITEM_CLOSE'))
                self._wait(self._storage_in_material, 'return to materials')

    def read_counts(self, keys):
        keys = tuple(dict.fromkeys(keys))
        if not keys or any(k not in ITEM_NAMES for k in keys):
            raise ValueError('Unsupported training inventory keys')
        self.device.screenshot()
        if self.config.SERVER != 'cn' or self.device.image.shape[:2] != (720, 1280):
            raise RequestHumanTakeover('Training inventory requires CN 1280x720')
        self.ui_goto_storage()
        self._storage_enter_material()
        self._wait_until_storage_stable()
        INVENTORY_SCROLL.set_top(main=self)
        self.device.sleep(0.5)
        counts = {}
        for _ in range(40):
            self.device.screenshot()
            if not self._storage_in_material():
                raise RequestHumanTakeover('Lost inventory material page during scan')
            for key in keys:
                if key in counts:
                    continue
                position = item_position(self.device.image, key)
                if position is not None:
                    counts[key] = self._read_item(key, position)
            if len(counts) == len(keys):
                return counts
            if INVENTORY_SCROLL.at_bottom(main=self):
                self.device.sleep(0.4)
                self.device.screenshot()
                if not INVENTORY_SCROLL.at_bottom(main=self):
                    raise RequestHumanTakeover('Inventory bottom is unstable')
                # Absence cannot distinguish zero stock from an unrecognized icon.
                for key in keys:
                    if key not in counts:
                        position = item_position(self.device.image, key)
                        if position is None:
                            raise RequestHumanTakeover('Inventory item absent or unrecognized: ' + key)
                        counts[key] = self._read_item(key, position)
                logger.info(f'Complete inventory scan: {counts}')
                return counts
            before = INVENTORY_SCROLL.cal_position(main=self)
            INVENTORY_SCROLL.next_page(main=self, page=0.45)
            self.device.sleep(0.5)
            self.device.screenshot()
            after = INVENTORY_SCROLL.cal_position(main=self)
            if after <= before + 0.001:
                raise RequestHumanTakeover('Inventory scan stopped before verified bottom')
        raise RequestHumanTakeover('Inventory scan exceeded page bound')
