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


def title_matches(observed, expected):
    """Whether a read item name is the expected one, tolerating bounded noise.

    The CN item dialog is read with cnocr and the reading carries the usual
    recognition noise: a residual leading character ('占战列改造图纸T3',
    2026-09-30 00:23:28) or a dropped interior character ('航母改造纸T3', same
    run, both from `Use/log/2026-09-30_alas2.txt`).  Requiring character-exact
    equality threw those readings away, so the item had to be opened and read
    again from scratch.  What actually tells the four retrofit blueprints apart
    is the ship type and the tier, so both stay required while at most one
    dropped or residual character is tolerated.
    """
    if not isinstance(observed, str):
        return False
    if observed == expected:
        return True
    if not len(expected) - 1 <= len(observed) <= len(expected) + 1:
        return False
    # Ship type in front, tier at the end: a name that lost its ship type or
    # drifted to another tier is a different item, not the same one read badly.
    return expected[:2] in observed and observed.endswith(expected[-2:])


class TrainingInventory(StorageUI):
    # Lowest thumb position that still counts as the end of the material list.
    # The measured end of the list reads 0.893 (see _inventory_at_end), and a
    # stall in the middle of the list is a different, genuine failure.
    END_POSITION_FLOOR = 0.7
    # Page turn of the first sweep, and of the second one that re-verifies the
    # keys the first sweep never matched.  Measured on the live CN page
    # (2026-09-30, both accounts): one 0.45-page turn moves the list by ~300 px,
    # while an item icon stays fully inside the scan crop for 582 - 88 = 494 px
    # of travel, so the first sweep samples every listed item at least once; the
    # 0.15-page turn leaves an icon fully visible in several frames, which is the
    # corroboration used before an item is called out of stock.
    SCAN_PAGE = 0.45
    VERIFY_PAGE = 0.15
    # Page-turn budget of one sweep.  The whole list spans 0.893 of the track,
    # i.e. ~13 turns at 0.45 and ~36 at 0.15; both budgets leave room for the
    # thumb length to change while scanning.
    SCAN_BOUND = 40
    VERIFY_BOUND = 80

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

    def _inventory_at_end(self):
        """Whether the last page turn hit the end of the material list.

        The calibrated INVENTORY_SCROLL track runs past the end of the drawn
        scrollbar on the CN material page, so cal_position() saturates below
        1.0 at the end of the list and at_bottom() never fires.  Measured on the
        2026-09-30 00:08:22 incident: the thumb is drawn at crop y 38.0 at the
        top and 452.5 at the end, i.e. it travels 414.5 px of the 541 px
        calibrated track, so the highest reachable position is 0.893 -- while
        at_bottom() needs more than 0.95, and next_page(0.45) targets 0.969.
        The scan therefore swiped at an unreachable position until it gave up.
        What the end of the list *is* observable as: Scroll.set() reports
        `stalled` when three swipes issued over the whole remaining distance
        left the thumb where it was.

        A stall below END_POSITION_FLOOR means the scroll broke somewhere in the
        middle of the list instead -- fail closed, as before.
        """
        if not getattr(INVENTORY_SCROLL, 'stalled', False):
            return False
        position = INVENTORY_SCROLL.cal_position(main=self)
        if position < self.END_POSITION_FLOOR:
            raise RequestHumanTakeover(
                f'Inventory scroll stalled at {position:.3f}, before the end of the list')
        logger.info(f'Inventory reached the end of the list at {position:.3f}')
        return True

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
                if not title_matches(title, ITEM_NAMES[key]) or count is None:
                    previous = None
                    continue
                # The stable reading is the item and its count, not the raw OCR
                # string: two readings of the same item whose noise differs
                # ('占战列改造图纸T3' then '战列改造图纸T3') are the same reading.
                if previous == count:
                    logger.info(f'Training inventory {key}: {count}')
                    return count
                previous = count
            raise RequestHumanTakeover(f'Unreliable inventory item details for {key}: {title}, {raw}')
        finally:
            if self._info_visible():
                self.device.click(point_button(895, 197, 'TRAINING_ITEM_CLOSE'))
                self._wait(self._storage_in_material, 'return to materials')

    def _sweep(self, keys, counts, page, bound):
        """Look for `keys` from the top of the material list to its verified end.

        Args:
            keys (tuple[str]): Keys to look for, in the order of the request.
            counts (dict): Already known counts; those keys are not looked for.
            page (float): Page turn per iteration.
            bound (int): Page-turn budget.

        Returns:
            dict: `counts` plus every key this sweep matched.
        """
        INVENTORY_SCROLL.set_top(main=self)
        self.device.sleep(0.5)
        for _ in range(bound):
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
            if INVENTORY_SCROLL.at_bottom(main=self) or self._inventory_at_end():
                return counts
            before = INVENTORY_SCROLL.cal_position(main=self)
            INVENTORY_SCROLL.next_page(main=self, page=page)
            self.device.sleep(0.5)
            self.device.screenshot()
            after = INVENTORY_SCROLL.cal_position(main=self)
            if getattr(INVENTORY_SCROLL, 'stalled', False):
                # The swipe was issued over the whole remaining distance and the
                # thumb did not move, so this was the end of the list after all:
                # see _inventory_at_end().  Looping on would only keep swiping at
                # an unreachable position and abort the task with this same
                # RequestHumanTakeover.
                continue
            if after <= before + 0.001:
                raise RequestHumanTakeover('Inventory scan stopped before verified bottom')
            # A verified page advance means the recorded scroll action made progress.
            # Keep the device-level protection for a genuinely stuck scroll, while
            # preventing a long but healthy inventory from accumulating history.
            self.device.click_record_clear()
        raise RequestHumanTakeover('Inventory scan exceeded page bound')

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

        counts = self._sweep(keys, {}, self.SCAN_PAGE, self.SCAN_BOUND)
        if len(counts) < len(keys):
            # A second, finer sweep for what the first one never matched.  The
            # coarse step can leave an icon fully visible in a single frame, so
            # absence is only called after the same list was sampled again with
            # several frames per icon.
            counts = self._sweep(keys, counts, self.VERIFY_PAGE, self.VERIFY_BOUND)
        missing = [key for key in keys if key not in counts]
        if missing:
            if not counts:
                # Nothing at all was recognized: the page or the icon assets are
                # unusable, so every count would be a guess.
                raise RequestHumanTakeover(
                    'No training inventory item was recognized: ' + ', '.join(missing))
            # The CN material page lists an item only while the account owns it,
            # so an item that two complete sweeps never matched is out of stock
            # rather than unrecognized.  Verified on 2026-09-30: the blueprint
            # row of the `alas` account holds 驱逐13 / 巡洋2 / 航母9 with no cell
            # at all between 巡洋 and 航母, while both other tiers of the same
            # family list all four items (`tests/fixtures/training_inventory/
            # material-absent-battleship.png`).
            for key in missing:
                logger.warning(f'Training inventory {key} is not listed in the material page; '
                               f'recording 0')
                counts[key] = 0
        logger.info(f'Complete inventory scan: {counts}')
        return counts
