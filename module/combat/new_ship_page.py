"""The `NEW SHIP ACQUIRED` page that blocks the battle status loops.

When a battle drops a ship that the account does not own yet, the game leaves the ship obtained
screen for the ship detail page of that ship: the `NEW SHIP ACQUIRED` banner, the ship portrait,
the side bar (评论 / 检视 / 锁定 / 分享), the 档案 panel and one blue 确定 button.  The page is not a
page of `Page` and no asset of the repository covers it, so the battle status loops polled it
until the device stuck check raised `GameStuckError: Wait too long`.
"""

from time import time

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, crop, random_rectangle_point
from module.logger import logger
from module.ocr.ocr import Ocr

# The confirm button of the page, measured on the archived frames of the error dumps
# 1785374923997 ... 1789931082750 (2026-07-30 ... 2026-09-21): a flat blue button of 175 x 59 px
# at (993, 602, 1168, 661), labelled 确定.  The search area is the bottom right corner, where the
# button sits, and the bounds only reject the blobs of other screens (blue buttons of 100-280 px
# wide are the ones that carry a label).
CONFIRM_BUTTON_COLOR = (87, 138, 201)
CONFIRM_SEARCH_AREA = (900, 560, 1280, 720)
CONFIRM_SIMILARITY = 200
CONFIRM_MIN_AREA = 3000
CONFIRM_MIN_WIDTH = 100
CONFIRM_MAX_WIDTH = 280
CONFIRM_MIN_HEIGHT = 35
CONFIRM_MAX_HEIGHT = 100
CONFIRM_MIN_ASPECT = 1.5
CONFIRM_MAX_ASPECT = 5.0

# Labels of a confirm button: cn and tw print 确定, jp prints 確定 or 確認.
CONFIRM_LABELS = ('确定', '確定', '確認', '确认')
# An OCRed label is compared by how much of it still agrees with one of the labels, so that a
# dropped, a wrong and a residual character all keep the button recognizable.  The confirm button
# of the META beacon page is blue as well and is read as 领励, which agrees with no label.
CONFIRM_LABEL_THRESHOLD = 0.5

# Interval between two clicks, clicks spent on the page that is on the display right now, and the
# time of the last click, to tell a still blocked page from a new one.  The same shape as
# module.combat.battle_result.
confirm_click_timer = Timer(2, count=0)
confirm_attempt = 0
confirm_clicked_at = 0.
CONFIRM_MAX_ATTEMPT = 3
CONFIRM_STALE = 10

# The label of the button is the only OCR of this module and its area is the button that was found,
# so the Ocr object is reused and its area is set per frame.
confirm_ocr = Ocr(CONFIRM_SEARCH_AREA, lang='cnocr', letter=(255, 255, 255), threshold=128,
                  name='NEW_SHIP_CONFIRM')


def cjk_only(text):
    """Drop everything an OCR result carries besides han characters, such as spaces and residue.

    Args:
        text (str): OCR result.

    Returns:
        str: Han characters of the result.
    """
    return ''.join(char for char in text or '' if '\u4e00' <= char <= '\u9fff')


def confirm_label_similarity(text, label):
    """Longest common subsequence ratio of an OCRed label and an expected one.

    A reading of the label may drop a character, mangle one or carry a character of the
    surroundings, so an exact comparison would lose the button.  This is the same measure as
    module.shipyard.development_assets.ship_name_similarity().

    Args:
        text (str): Han characters of the OCR result.
        label (str): Expected label.

    Returns:
        float: 0 to 1.
    """
    if not text:
        return 0.0
    previous = [0] * (len(label) + 1)
    for char_a in text:
        current = [0]
        for index, char_b in enumerate(label, 1):
            if char_a == char_b:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1] / max(len(text), len(label))


def is_confirm_label(text):
    """Check an OCRed button label against the confirm vocabulary.

    Args:
        text (str): OCR result.

    Returns:
        bool: If the label is a confirm label.
    """
    letters = cjk_only(text)
    # A label of a button is short.  A long result is the surroundings of a button that was
    # localized wrongly, not a confirm label.
    if not letters or len(letters) > 6:
        return False

    return max(confirm_label_similarity(letters, label) for label in CONFIRM_LABELS) \
        >= CONFIRM_LABEL_THRESHOLD


def find_confirm_button_area(image):
    """Locate the blue confirm button of the page.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y) of the button, or None.
    """
    region = crop(image, CONFIRM_SEARCH_AREA)
    mask = (color_similarity_2d(region, color=CONFIRM_BUTTON_COLOR) > CONFIRM_SIMILARITY).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    best = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < CONFIRM_MIN_AREA:
            continue
        if not CONFIRM_MIN_WIDTH <= width <= CONFIRM_MAX_WIDTH:
            continue
        if not CONFIRM_MIN_HEIGHT <= height <= CONFIRM_MAX_HEIGHT:
            continue
        if not CONFIRM_MIN_ASPECT <= width / height <= CONFIRM_MAX_ASPECT:
            continue
        if best is None or area > best[4]:
            best = (x, y, width, height, area)

    if best is None:
        return None

    x, y, width, height, _ = best
    return (x + CONFIRM_SEARCH_AREA[0], y + CONFIRM_SEARCH_AREA[1],
            x + width + CONFIRM_SEARCH_AREA[0], y + height + CONFIRM_SEARCH_AREA[1])


def match_new_ship_confirm(image):
    """Detect the `NEW SHIP ACQUIRED` page and localize its confirm button.

    The button is recognized by its blue body and by its label, and it is localized by the same
    measurement, so no screen layout is assumed: the click target is the button that was read,
    not a fixed coordinate.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        Button: The confirm button of the page, or None.
    """
    area = find_confirm_button_area(image)
    if area is None:
        return None

    confirm_ocr.buttons = area
    if not is_confirm_label(confirm_ocr.ocr(image)):
        return None

    return Button(area=area, color=CONFIRM_BUTTON_COLOR, button=area, name='NEW_SHIP_CONFIRM')


def handle_new_ship_page(app):
    """Skip a `NEW SHIP ACQUIRED` page that is left on the display.

    Live log/error/1789931082750 (2026-09-21 03:04:42, GemsFarming on campaign 2-4): the battle
    dropped 大斗犬 for the first time, so the game left the ship obtained screen for the ship
    detail page of that ship.  `AutoSearchCombat.auto_search_combat_status()` polls the result
    screen, the item popup, the ship popup and the exp popup, and none of them matches this page,
    so the loop ran into the stuck check of the device: `GameStuckError: Wait too long`.  The same
    page and the same loop are behind nine older dumps, from 2026-07-30 to 2026-09-07, all of them
    after `Click @ GET_SHIP`.

    The click is repeated CONFIRM_MAX_ATTEMPT times because a single click can be swallowed by the
    game, and then the page is left to the loop, which reports it through the stuck check as
    before.

    Args:
        app: Alas instance.

    Returns:
        bool: If clicked.
    """
    global confirm_attempt, confirm_clicked_at

    if not confirm_click_timer.reached():
        return False

    button = match_new_ship_confirm(app.device.image)
    if button is None:
        confirm_attempt = 0
        return False

    # A page that is still there long after the last click belongs to a new battle.
    if time() - confirm_clicked_at > CONFIRM_STALE:
        confirm_attempt = 0

    if confirm_attempt >= CONFIRM_MAX_ATTEMPT:
        logger.warning(f'Unable to skip the new ship page: {button}')
        return False

    point = random_rectangle_point(button.button)
    confirm_attempt += 1
    confirm_clicked_at = time()
    logger.info(f'Skip new ship page: {button}, click {point}, attempt {confirm_attempt}')
    app.device.click(point)
    confirm_click_timer.reset()
    return True
