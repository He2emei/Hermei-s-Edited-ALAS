from datetime import datetime
import re

import cv2
import numpy as np
from PIL import Image
from module.base.button import Button
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.freebies.assets import BUY_CONFIRM
from module.logger import logger
from module.ocr.ocr import Ocr
from module.ui.page import page_main
from module.ui.ui import UI


EVENT_HEADER = '飓风的藏宝地'
ENTRY_LABEL = '限时活动'
EVENT_NAME_PREFIX = '船团宝藏回馈'
EVENT_ROMAN = frozenset(('I', 'II', 'III', 'IV', 'V', 'VI', 'VII'))
EVENT_ROMAN_NORMALIZE = str.maketrans({'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV',
                                      'Ⅴ': 'V', 'Ⅵ': 'VI', 'Ⅶ': 'VII'})

EVENT_ENTRY_ICON = Button(area=(956, 80, 1045, 106), color=(80, 100, 130),
                          button=(956, 80, 1045, 106),
                          file='./assets/cn/freebies/LIMITED_EVENT_ENTRY_ICON.png',
                          name='LIMITED_EVENT_ENTRY_ICON')
EVENT_PREVIEW_CANCEL = Button(area=(408, 578, 583, 638), color=(100, 100, 100),
                              button=(408, 578, 583, 638),
                              file='./assets/cn/freebies/EVENT_SUPPLY_PREVIEW_CANCEL.png')
EVENT_CONFIRM_CANCEL = Button(area=(402, 482, 579, 541), color=(100, 100, 100),
                              button=(402, 482, 579, 541),
                              file='./assets/cn/freebies/EVENT_SUPPLY_CONFIRM_CANCEL.png')
EVENT_CONFIRM_BLUE = Button(area=(702, 482, 878, 541), color=(80, 120, 180),
                            button=(702, 482, 878, 541),
                            file='./assets/cn/freebies/EVENT_SUPPLY_CONFIRM_BLUE.png')
EVENT_HOME = Button(area=(1212, 20, 1268, 80), color=(160, 160, 160),
                    button=(1212, 20, 1268, 80),
                    file='./assets/cn/freebies/EVENT_SUPPLY_HOME.png')


def point_button(x, y, name):
    """A tiny click target centered on a coordinate validated by OCR evidence."""
    return Button(area=(x - 1, y - 1, x + 1, y + 1), color=(0, 0, 0),
                  button=(x - 1, y - 1, x + 1, y + 1), name=name)

# The dated CN rerun is the only supported event. Do not infer that a later
# event using a similar screen has the same prices or purchase flow.
def event_window(now=None):
    now = now or datetime.now()
    return now.year == 2026 and (now.month == 10 and now.day >= 22 or now.month == 11 and now.day <= 4)


def exact_zero(value):
    return str(value).strip() == '0'


def canonical_event_name(value):
    value = str(value).strip().replace(' ', '')
    if not value.startswith(EVENT_NAME_PREFIX):
        return None
    roman = value[len(EVENT_NAME_PREFIX):]
    roman = roman.translate(EVENT_ROMAN_NORMALIZE)
    # Preserve OCR glyphs such as lowercase l. They may look like Roman I,
    # but we do not infer a tier from that resemblance.
    if roman in EVENT_ROMAN or (set(roman) == {'l'} and 1 <= len(roman) <= 3):
        return EVENT_NAME_PREFIX + roman
    return None


def has_convoy_base_name(value):
    value = str(value).strip().replace(' ', '').translate(EVENT_ROMAN_NORMALIZE)
    if value == EVENT_NAME_PREFIX:
        return True
    return value.startswith(EVENT_NAME_PREFIX) and re.fullmatch(
        r'[IVXivxlL]+', value[len(EVENT_NAME_PREFIX):]) is not None


def valid_listing(name1, count1, claim1, name2, count2, claim2):
    event_name = canonical_event_name(name1)
    return (event_name is not None and canonical_event_name(name2) == event_name
            and _available_count(count1) and _available_count(count2)
            and claim1 and claim2)


def _available_count(value):
    value = str(value).replace(' ', '').replace('：', ':')
    return re.fullmatch(r'(可)?购买次数:?1/1', value) is not None


def is_zero_event_prompt(white, green):
    return (str(white).strip() == '是否使用购买'
            and str(green).strip().startswith('0钻石' + EVENT_NAME_PREFIX))


def claim_label_matches(image_crop):
    template = np.asarray(Image.open('./assets/cn/freebies/EVENT_CLAIM_LABEL.png').convert('RGB'))
    if template is None or image_crop.ndim != 3 or image_crop.shape[0] < template.shape[0] or image_crop.shape[1] < template.shape[1]:
        return False
    match = cv2.matchTemplate(image_crop, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, _ = cv2.minMaxLoc(match)
    return score >= 0.95


class EventSupply(UI):
    """Collect only this rerun's zero-diamond convoy reward."""

    def _ocr(self, areas):
        result = Ocr(areas, lang='cnocr', name='EventSupplyEvidence').ocr(self.device.image)
        return result if isinstance(result, list) else [result]

    def _is_home(self):
        return (getattr(self.config, 'SERVER', '') == 'cn'
                and self.device.image.shape[:2] == (720, 1280)
                and self.ui_page_appear(page_main, offset=(5, 5)))

    def _entry(self):
        # Exact label in the fixed first event tile; require the game's native
        # home-page detector first, so an unknown activity is never entered.
        if not self.appear(EVENT_ENTRY_ICON, offset=(5, 5)):
            return False
        label = self._ocr([(956, 162, 1045, 188)])[0]
        if str(label).strip() != ENTRY_LABEL:
            return False
        self.device.click(point_button(1000, 120, 'EVENT_SUPPLY_ENTRY'))
        return True

    def _listing_header(self):
        if self.device.image.shape[:2] != (720, 1280):
            return False
        first = self._ocr([(25, 319, 180, 349)])[0]
        self.device.screenshot()
        second = self._ocr([(25, 319, 180, 349)])[0]
        return str(first).strip() == EVENT_HEADER and str(second).strip() == EVENT_HEADER

    def _card_evidence(self, x):
        prefix = str(self._ocr([(x + 30, 402, x + 149, 430)])[0]).strip()
        suffix = str(self._ocr([(x + 153, 402, x + 178, 430)])[0]).strip().translate(EVENT_ROMAN_NORMALIZE)
        name = prefix + suffix if prefix == EVENT_NAME_PREFIX else ''
        count = str(self._ocr([(x + 54, 499, x + 174, 521)])[0]).strip()
        label = self.device.image[560:588, x:x + 200]
        return name, count, claim_label_matches(label)

    def _find_claimable(self):
        # Names/counts/buttons are read twice from the same identified card.
        # The other cards (including the ¥6 offers) are never clicked.
        for x in (321, 544, 766, 990):
            first = self._card_evidence(x)
            self.device.screenshot()
            if not self._listing_header():
                from module.exception import GamePageUnknownError
                raise GamePageUnknownError('Lost event-list identity while scanning cards')
            second = self._card_evidence(x)
            if valid_listing(*first, *second):
                return x + 100, canonical_event_name(first[0])
        return None

    def _preview_is_free(self):
        name = str(self._ocr([(270, 425, 398, 460)])[0]).strip()
        price = str(self._ocr([(655, 505, 701, 547)])[0]).strip()
        has_buy = self.appear(BUY_CONFIRM, offset=(20, 20))
        target = getattr(self, 'target_name', None)
        if (target is None or not has_convoy_base_name(name) or not has_buy
                or not self.appear(EVENT_PREVIEW_CANCEL, offset=(10, 10))):
            return None
        self.device.screenshot()
        name2 = str(self._ocr([(270, 425, 398, 460)])[0]).strip()
        price2 = str(self._ocr([(655, 505, 701, 547)])[0]).strip()
        has_buy2 = self.appear(BUY_CONFIRM, offset=(20, 20))
        has_cancel2 = self.appear(EVENT_PREVIEW_CANCEL, offset=(10, 10))
        if not has_convoy_base_name(name2) or not has_buy2 or not has_cancel2:
            return None
        if exact_zero(price) and exact_zero(price2):
            return True
        # The preview identity and both controls are known; any nonzero or
        # unreadable price is a refusal and is cancelled by the caller.
        return False

    def _zero_confirmation(self):
        # No generic popup confirmation: the entire action hinges on exact
        # Chinese prompt text, exact name, and an independently observed 0.
        prompt_area = (435, 330, 840, 365)
        white_ocr = Ocr([prompt_area], lang='cnocr', letter=(255, 255, 247), threshold=100,
                        name='EventSupplyConfirmWhite')
        green_ocr = Ocr([prompt_area], lang='cnocr', letter=(146, 252, 99), threshold=100,
                        name='EventSupplyConfirmGreen')
        first_white = str(white_ocr.ocr(self.device.image)).strip()
        first_green = str(green_ocr.ocr(self.device.image)).strip()
        cancel1 = self.appear(EVENT_CONFIRM_CANCEL, offset=(10, 10))
        confirm1 = self.appear(EVENT_CONFIRM_BLUE, offset=(10, 10))
        self.device.screenshot()
        second_white = str(white_ocr.ocr(self.device.image)).strip()
        second_green = str(green_ocr.ocr(self.device.image)).strip()
        cancel2 = self.appear(EVENT_CONFIRM_CANCEL, offset=(10, 10))
        confirm2 = self.appear(EVENT_CONFIRM_BLUE, offset=(10, 10))
        target = getattr(self, 'target_name', None)
        if (target and is_zero_event_prompt(first_white, first_green)
                and is_zero_event_prompt(second_white, second_green)
                and cancel1 and confirm1 and cancel2 and confirm2):
            self.device.click(EVENT_CONFIRM_BLUE)
            return True
        known_dialog = (first_white == '是否使用购买' and second_white == '是否使用购买'
                        and cancel1 and confirm1 and cancel2 and confirm2)
        if target and known_dialog:
            return False
        # Any nonzero or unreadable amount on this known confirmation is
        # safely cancelled by the caller, never confirmed.
        return None

    def _return_home(self):
        if not self.appear(EVENT_HOME, offset=(5, 5)):
            return self._is_home()
        self.device.click(EVENT_HOME)
        for _ in range(6):
            self.device.screenshot()
            if self._is_home():
                return True
        return False

    def _finish_home(self):
        from module.exception import GamePageUnknownError
        if not self._return_home():
            raise GamePageUnknownError('Could not verify return to page_main after event supply')

    def _claim_candidate(self, candidate):
        from module.exception import GamePageUnknownError
        claim, self.target_name = candidate
        if self.target_name is None:
            raise GamePageUnknownError('Could not retain exact convoy reward tier')
        self.device.click(point_button(claim, 330, 'EVENT_SUPPLY_REWARD_CARD'))
        preview = None
        for _ in range(10):
            self.device.screenshot()
            preview = self._preview_is_free()
            if preview is not None:
                break
        if preview is None:
            if self._return_home():
                return False
            raise GamePageUnknownError('Unknown limited-event purchase preview')
        if not preview:
            if not self.appear(EVENT_PREVIEW_CANCEL, offset=(10, 10)):
                raise GamePageUnknownError('Cannot safely cancel unknown event preview')
            self.device.click(EVENT_PREVIEW_CANCEL)
            self.device.screenshot()
            if self._listing_header():
                return False
            raise GamePageUnknownError('Could not verify return to event list after preview cancel')
        self.device.click(BUY_CONFIRM)
        confirmation = None
        for _ in range(10):
            self.device.screenshot()
            confirmation = self._zero_confirmation()
            if confirmation is not None:
                break
        if confirmation is False:
            if not self.appear(EVENT_CONFIRM_CANCEL, offset=(10, 10)):
                raise GamePageUnknownError('Cannot safely cancel unknown confirmation')
            self.device.click(EVENT_CONFIRM_CANCEL)
            self.device.screenshot()
            if self._listing_header():
                return False
            raise GamePageUnknownError('Could not verify return to event list after confirmation cancel')
        if confirmation is not True:
            raise GamePageUnknownError('Unknown limited-event purchase confirmation')

        # Do not repeat the purchase if its result is ambiguous.
        item_button = None
        for _ in range(10):
            self.device.screenshot()
            if self.appear(GET_ITEMS_1, offset=20):
                item_button = GET_ITEMS_1
                break
            if self.appear(GET_ITEMS_2, offset=20):
                item_button = GET_ITEMS_2
                break
        if item_button is None:
            raise GamePageUnknownError('Event supply purchase result is unverified')
        self.device.click(item_button)
        listed = False
        for _ in range(10):
            if self._listing_header():
                listed = True
                break
            self.device.screenshot()
        if not listed:
            raise GamePageUnknownError('Event supply reward list is unverified after GET_ITEMS')
        return True

    def run(self):
        if not event_window():
            logger.info('Event convoy freebie is outside its verified date window')
            return False
        if getattr(self.config, 'SERVER', '') != 'cn':
            logger.info('Event convoy freebie is supported only on CN')
            return False
        self.ui_ensure(page_main)
        if not self._is_home() or not self._entry():
            logger.info('No verified current event entry; skipping convoy freebie')
            return False

        # Once entered, only the exact page identity permits list navigation.
        transitioned = False
        for _ in range(6):
            if self._listing_header():
                transitioned = True
                break
            self.device.screenshot()
        if not transitioned:
            if self._return_home():
                return False
            from module.exception import GamePageUnknownError
            raise GamePageUnknownError('Unknown limited-event page after entry')
        collected = False
        remaining_swipes = 5
        for _ in range(7):
            candidate = self._find_claimable()
            while candidate is None and remaining_swipes:
                self.device.swipe((1110, 370), (430, 370), name='EVENT_SUPPLY_LIST')
                self.device.screenshot()
                remaining_swipes -= 1
                if not self._listing_header():
                    from module.exception import GamePageUnknownError
                    raise GamePageUnknownError('Lost event-list identity during scroll')
                candidate = self._find_claimable()
            if candidate is None:
                break
            if not self._claim_candidate(candidate):
                self._finish_home()
                return collected
            collected = True
        self._finish_home()
        return collected
