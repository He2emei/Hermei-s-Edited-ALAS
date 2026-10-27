from calendar import day_name
import re

import cv2

from module.base.timer import Timer
from module.base.utils import crop
from module.base.button import Button
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.config.utils import get_server_weekday
from module.freebies.assets import *
from module.logger import logger
from module.ocr.ocr import Digit
from module.ocr.ocr import Ocr
from module.shop.assets import SHOP_OCR_OIL, SHOP_OCR_OIL_CHECK
from module.ui.page import page_shop, page_supply_pack


SUPPLY_PACK_PREVIEW_CANCEL = Button(
    area={'cn': (408, 578, 583, 638)}, color={'cn': (157, 158, 159)},
    button={'cn': (408, 578, 583, 638)},
    file={'cn': './assets/cn/freebies/SUPPLY_PACK_PREVIEW_CANCEL.png'},
    name='SUPPLY_PACK_PREVIEW_CANCEL')
SUPPLY_PACK_CONFIRM_CANCEL = Button(
    area={'cn': (402, 482, 579, 541)}, color={'cn': (165, 167, 167)},
    button={'cn': (402, 482, 579, 541)},
    file={'cn': './assets/cn/freebies/SUPPLY_PACK_CONFIRM_CANCEL.png'},
    name='SUPPLY_PACK_CONFIRM_CANCEL')
SUPPLY_PACK_CONFIRM_BLUE = Button(
    area={'cn': (702, 482, 878, 541)}, color={'cn': (96, 143, 199)},
    button={'cn': (702, 482, 878, 541)},
    file={'cn': './assets/cn/freebies/SUPPLY_PACK_CONFIRM_BLUE.png'},
    name='SUPPLY_PACK_CONFIRM_BLUE')
SUPPLY_PACK_PREVIEW_NAME = (270, 425, 435, 460)
SUPPLY_PACK_PRICE_AREA = (650, 505, 710, 547)
SUPPLY_PACK_PRICE_TEXT = (655, 505, 710, 547)
SUPPLY_PACK_CONFIRM_TEXT = (435, 330, 840, 365)


class SupplyPack(CampaignStatus):
    def supply_pack_find(self, supply_pack, skip_first_screenshot=True):
        """
        Find a supply pack with at most 8 leftward swipes.

        Returns:
            bool: If found.
        """
        for _ in range(9):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(supply_pack, offset=(0, -20, 400, 20)):
                return True
            self.device.swipe_vector((-400, 0), box=(230, 200, 1060, 600))            

        logger.warning(f'Supply pack {supply_pack} not found after 8 swipes')
        return False

    def _scan_weekly_free_price(self, max_swipes=8):
        """Search the horizontal offer list for the legacy free-price marker.

        The marker alone does not prove the contents of its purchase dialog;
        a stable match only opens the card preview, which has separate gates.
        """
        max_swipes = min(10, max(0, int(max_swipes)))
        list_area = (195, 180, 1000, 665)
        previous = None
        for swipe in range(max_swipes + 1):
            if not self.match_template_color(page_supply_pack.check_button, offset=(20, 20)):
                return False
            if self.appear(FREE_SUPPLY_PACK, offset=(700, 12)):
                first_target = tuple(FREE_SUPPLY_PACK.button)
                self.device.screenshot()
                if self.appear(FREE_SUPPLY_PACK, offset=(700, 12)) \
                        and tuple(FREE_SUPPLY_PACK.button) == first_target:
                    self.device.click(FREE_SUPPLY_PACK)
                    return True
            current = crop(self.device.image, list_area, copy=True)
            if previous is not None:
                progress = cv2.absdiff(current, previous).mean()
                if progress < 1.0:
                    logger.info('Weekly offer-pack list stopped advancing; end bounded scan')
                    return False
                # Only clear gesture history after measured card-list progress.
                self.device.click_record_clear()
            if swipe == max_swipes:
                break
            previous = current
            self.device.swipe_vector((-700, 0), box=list_area, duration=(0.4, 0.6))
            self.device.sleep(0.6)
            self.device.screenshot()
        return False

    def _ocr_text(self, area, letter=(255, 255, 255), threshold=100):
        return str(Ocr([area], lang='cnocr', letter=letter, threshold=threshold,
                       name='SupplyPackEvidence').ocr(self.device.image)).strip()

    def _wait_for(self, predicate, attempts=6):
        for _ in range(attempts):
            self.device.screenshot()
            if predicate():
                return True
            self.device.sleep(0.2)
        return False

    def _preview_controls(self):
        return (self.appear(BUY_CONFIRM, offset=(20, 20))
                and self.appear(SUPPLY_PACK_PREVIEW_CANCEL, offset=(10, 10)))

    def _confirm_controls(self):
        return (self.appear(SUPPLY_PACK_CONFIRM_CANCEL, offset=(10, 10))
                and self.appear(SUPPLY_PACK_CONFIRM_BLUE, offset=(10, 10)))

    def _preview_evidence(self):
        """Return (name, free) only from two stable, readable preview frames."""
        if not self._preview_controls():
            return None
        name1 = self._ocr_text(SUPPLY_PACK_PREVIEW_NAME)
        raw_price1 = self._ocr_text(SUPPLY_PACK_PRICE_AREA)
        price1 = self._ocr_text(SUPPLY_PACK_PRICE_TEXT)
        self.device.screenshot()
        name2 = self._ocr_text(SUPPLY_PACK_PREVIEW_NAME)
        raw_price2 = self._ocr_text(SUPPLY_PACK_PRICE_AREA)
        price2 = self._ocr_text(SUPPLY_PACK_PRICE_TEXT)
        if not self._preview_controls() or not name1 or name1 != name2:
            return None
        if price1 == '0' and price2 == '0' and raw_price1 == '0' and raw_price2 == '0':
            return name1, True
        if price1 and price2 and raw_price1 and raw_price2:
            return name1, False
        return None

    def _cancel_pack_preview(self):
        from module.exception import GamePageUnknownError
        if not self._preview_controls():
            raise GamePageUnknownError('Unknown weekly supply pack preview; cannot safely cancel')
        self.device.click(SUPPLY_PACK_PREVIEW_CANCEL)
        if not self._wait_for(lambda: self.match_template_color(page_supply_pack.check_button, offset=(20, 20))):
            raise GamePageUnknownError('Could not verify offer-pack list after cancelling preview')
        return True

    def _confirmation_decision(self, white, green, pack_name):
        white = str(white).strip()
        green = str(green).strip().replace(' ', '')
        if white != '是否使用购买':
            return None
        prefix = re.fullmatch(r'(\d+)钻石(.+)', green)
        if not prefix or prefix.group(2) != pack_name.replace(' ', ''):
            return False
        return prefix.group(1) == '0'

    def _read_confirmation(self, pack_name):
        if not self._confirm_controls():
            return None
        first_white = self._ocr_text(SUPPLY_PACK_CONFIRM_TEXT, letter=(255, 255, 247))
        first_green = self._ocr_text(SUPPLY_PACK_CONFIRM_TEXT, letter=(146, 252, 99))
        self.device.screenshot()
        second_white = self._ocr_text(SUPPLY_PACK_CONFIRM_TEXT, letter=(255, 255, 247))
        second_green = self._ocr_text(SUPPLY_PACK_CONFIRM_TEXT, letter=(146, 252, 99))
        buttons2 = self._confirm_controls()
        if not buttons2:
            return None
        first = self._confirmation_decision(first_white, first_green, pack_name)
        second = self._confirmation_decision(second_white, second_green, pack_name)
        return first if first is not None and first == second else None

    def _collect_verified_purchase(self, wait=False):
        from module.exception import GamePageUnknownError
        got_items = self.appear(GET_ITEMS_1, offset=(30, 30)) or self.appear(GET_ITEMS_2, offset=(30, 30))
        if not got_items and wait:
            got_items = self._wait_for(lambda: self.appear(GET_ITEMS_1, offset=(30, 30))
                                       or self.appear(GET_ITEMS_2, offset=(30, 30)))
        if not got_items:
            return False
        self.device.click(GET_ITEMS_1 if self.appear(GET_ITEMS_1, offset=(30, 30)) else GET_ITEMS_2)
        if not self._wait_for(lambda: self.match_template_color(page_supply_pack.check_button, offset=(20, 20))):
            raise GamePageUnknownError('Could not verify offer-pack list after collecting weekly supply pack')
        return True

    def _buy_cn_weekly_free(self):
        from module.exception import GamePageUnknownError
        if not self._scan_weekly_free_price():
            logger.info('No verified free weekly pack found in bounded offer-pack scan')
            return False
        if not self._wait_for(self._preview_controls):
            raise GamePageUnknownError('Weekly supply pack preview did not reach its known controls')
        preview = self._preview_evidence()
        if preview is None:
            logger.warning('Weekly supply pack preview is unknown; cancel only if its known controls are visible')
            self._cancel_pack_preview()
            return False
        pack_name, free = preview
        if not free:
            logger.info(f'Weekly supply pack is not free: {pack_name}; cancel preview')
            return self._cancel_pack_preview() and False
        # Purchase is the only click allowed after the exact two-frame 0 read.
        self.device.click(BUY_CONFIRM)
        transitioned = self._wait_for(lambda: self.appear(GET_ITEMS_1, offset=(30, 30))
                                      or self.appear(GET_ITEMS_2, offset=(30, 30))
                                      or self._confirm_controls())
        if not transitioned:
            raise GamePageUnknownError('No known state after weekly supply pack purchase click; do not retry')
        if self._collect_verified_purchase():
            return True
        decision = self._read_confirmation(pack_name)
        if decision is False:
            if self._confirm_controls():
                self.device.click(SUPPLY_PACK_CONFIRM_CANCEL)
                if not self._wait_for(self._preview_controls):
                    raise GamePageUnknownError('Could not verify preview after cancelling unknown purchase confirmation')
                self._cancel_pack_preview()
            elif self._preview_controls():
                self._cancel_pack_preview()
            else:
                raise GamePageUnknownError('Unknown state after weekly pack purchase click; do not retry')
            return False
        if decision is None:
            logger.warning('Weekly supply pack confirmation is unknown; cancel known popup and do not retry')
            if self._confirm_controls():
                self.device.click(SUPPLY_PACK_CONFIRM_CANCEL)
                if not self._wait_for(self._preview_controls):
                    raise GamePageUnknownError('Could not verify preview after cancelling unknown purchase confirmation')
                self._cancel_pack_preview()
            elif self._preview_controls():
                self._cancel_pack_preview()
            else:
                raise GamePageUnknownError('Unknown state after weekly pack purchase click; do not retry')
            return False
        self.device.click(SUPPLY_PACK_CONFIRM_BLUE)
        if not self._collect_verified_purchase(wait=True):
            raise GamePageUnknownError('Weekly supply pack result not verified after zero confirmation')
        return True

    def supply_pack_buy(self, supply_pack, skip_first_screenshot=True):
        """
        Args:
            supply_pack (Button): Button of supply pack, click to buy.
            skip_first_screenshot (bool):

        Returns:
            bool: If bought.
        """
        logger.hr('Supply pack buy')
        if not self.supply_pack_find(supply_pack, skip_first_screenshot=skip_first_screenshot):
            return False
        [self.interval_clear(asset) for asset in [GET_ITEMS_1, GET_ITEMS_2, supply_pack, BUY_CONFIRM]]

        logger.info(f'Buying {supply_pack}')
        executed = False
        click_count = 0
        confirm_timer = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(supply_pack, offset=(200, 20), interval=3):
                if click_count >= 3:
                    logger.warning(f'Failed to buy {supply_pack} after 3 trail, probably reached resource limit, skip')
                    break
                self.device.click(supply_pack)
                click_count += 1
                confirm_timer.reset()
                continue
            if self.appear_then_click(BUY_CONFIRM, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm('BUY_SUPPLY_PACK'):
                self.interval_reset(supply_pack)
                self.interval_reset(BUY_CONFIRM)
                executed = True
                continue
            for button in [GET_ITEMS_1, GET_ITEMS_2]:
                if self.appear_then_click(button, offset=(30, 30), interval=3):
                    confirm_timer.reset()
                    continue

            # End
            if self.appear(page_supply_pack.check_button, offset=(20, 20)) \
                    and not self.appear(supply_pack, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        logger.info(f'Supply pack buy finished, executed={executed}')
        return executed

    def goto_supply_pack(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_shop
            out: page_supply_pack, supply pack tab
        """
        self.ui_goto(page_supply_pack, skip_first_screenshot=skip_first_screenshot)

    def run(self):
        """
        Pages:
            in: Any page
            out: page_supply_pack, supply pack tab
        """
        self.ui_ensure(page_shop)
        self.goto_supply_pack()
        if self.get_oil() < 21000:
            server_today = get_server_weekday()
            target = self.config.SupplyPack_DayOfWeek
            target_name = day_name[target]
            if server_today >= target:
                if getattr(self.config, 'SERVER', '') == 'cn':
                    self._buy_cn_weekly_free()
                else:
                    self.supply_pack_buy(FREE_SUPPLY_PACK)
            else:
                logger.info(f'Delaying free week supply pack to {target_name}')
        else:
            logger.info('Oil > 21000, unable to buy free weekly supply pack')


class SupplyPack_250814(SupplyPack):
    def get_oil(self, skip_first_screenshot=True):
        """
        Returns:
            int: Oil amount
        """
        amount = 0
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Get oil timeout')
                break

            if not self.appear(SHOP_OCR_OIL_CHECK, offset=(10, 2)):
                logger.info('No oil icon')
                continue
            ocr = Digit(SHOP_OCR_OIL, name='OCR_OIL', letter=(247, 247, 247), threshold=128)
            amount = ocr.ocr(self.device.image)
            if amount >= 100:
                break

        return amount

    def goto_supply_pack(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_shop
            out: page_supply_pack, supply pack tab
        """
        logger.info('Goto supply pack')
        for _ in self.loop():

            if self.match_template_color(page_supply_pack.check_button, offset=(20, 20)):
                logger.info('At supply pack')
                break

            elif self.appear_then_click(page_supply_pack.check_button, offset=(20, 20), interval=3):
                continue
