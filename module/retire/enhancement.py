from random import choice

import module.config.server as server
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_pad
from module.combat.assets import GET_ITEMS_1
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire.assets import *
from module.retire.dock import Dock
from module.ui.assets import BACK_ARROW

VALID_SHIP_TYPES = ['dd', 'ss', 'cl', 'ca', 'bb', 'cv', 'repair', 'others']
if server.server != 'jp':
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(255, 255, 255), threshold=192)
else:
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(201, 201, 201), threshold=192)

# Material slots of page_ship_enhance (CN 1280x720): 6 columns x 2 rows of 82x82
# px cells on a 92x94 px pitch, inside ENHANCE_AREA_FULL.  Measured on archived
# frames: the game draws the empty slot '+' at the centre of its cell (all ten
# '+' of the 2026-05-13 frame sit within 1.6 px of these centres) and
# EMPTY_ENHANCE_SLOT_PLUS's own asset area (737,402,773,437) is the first cell's
# centre (1.9 px off).  The portrait templates TEMPLATE_ENHANCE_* are 42x18 /
# 42x22 crops of the ship's eye region, which is *not* centred in the cell, so
# anything derived from a portrait match has to be snapped back to this grid.
ENHANCE_SLOT_ORIGIN = (713, 377)
ENHANCE_SLOT_PITCH = (92, 94)
ENHANCE_SLOT_SHAPE = (82, 82)
ENHANCE_SLOT_GRID_SHAPE = (6, 2)
ENHANCE_SLOT_COUNT = ENHANCE_SLOT_GRID_SHAPE[0] * ENHANCE_SLOT_GRID_SHAPE[1]

# Search window around a cell centre when looking for the empty slot '+'.  The
# game draws it within ~2 px of the centre, so 10 px is generous while staying
# far below the 92 px pitch, i.e. a neighbouring slot can never be picked up.
ENHANCE_SLOT_MATCH_OFFSET = 10
# Archived frames match the '+' asset at 0.86-0.98; a filled slot reads 0.27 and
# the material-selection list 0.51, so 0.8 keeps a margin on both sides.  A false
# "empty" only skips a de-select, a false "filled" clicks an empty slot, which
# opens the material-selection list.
ENHANCE_SLOT_MATCH_SIMILARITY = 0.8

# De-select clicks of one material slot.  Retries cover a swallowed touch, and
# the budget keeps the loop from spinning: Device.click_record_check() aborts the
# task after 12 clicks on one button.
ENHANCE_DESELECT_MAX_CLICK = 3
ENHANCE_DESELECT_CLICK_INTERVAL = 2

# Bottom bar of the material-selection list (选择强化材料, 已选中 N/12) that a click
# on an empty material slot opens.  Colors are the mean of the archived
# 2026-09-27 frame; the ship detail page reads (116,118,133) and (94,96,108) at
# the same areas, i.e. 102 and 96 apart in Photoshop tolerance.
ENHANCE_SELECT_CANCEL = Button(
    area=(714, 643, 886, 701), color=(176, 98, 91), button=(714, 643, 886, 701),
    name='ENHANCE_SELECT_CANCEL')
ENHANCE_SELECT_CONFIRM = Button(
    area=(960, 660, 1080, 695), color=(100, 143, 198), button=(960, 660, 1080, 695),
    name='ENHANCE_SELECT_CONFIRM')


def enhance_slot_center(index):
    """
    Args:
        index (int): Material slot index, row major, 0 to ENHANCE_SLOT_COUNT - 1

    Returns:
        tuple[float, float]: Center of that slot cell
    """
    row, col = divmod(index, ENHANCE_SLOT_GRID_SHAPE[0])
    return (ENHANCE_SLOT_ORIGIN[0] + col * ENHANCE_SLOT_PITCH[0] + ENHANCE_SLOT_SHAPE[0] / 2,
            ENHANCE_SLOT_ORIGIN[1] + row * ENHANCE_SLOT_PITCH[1] + ENHANCE_SLOT_SHAPE[1] / 2)


def enhance_slot_area(index):
    """
    Args:
        index (int): Material slot index, row major

    Returns:
        tuple: The area the game draws the empty slot '+' in, i.e. the clickable
               centre of that material card.  Archived runs clicked there and
               de-selected the material, so it is the verified click target.
    """
    cx, cy = enhance_slot_center(index)
    w = EMPTY_ENHANCE_SLOT_PLUS.area[2] - EMPTY_ENHANCE_SLOT_PLUS.area[0]
    h = EMPTY_ENHANCE_SLOT_PLUS.area[3] - EMPTY_ENHANCE_SLOT_PLUS.area[1]
    return (int(round(cx - w / 2)), int(round(cy - h / 2)),
            int(round(cx + w / 2)), int(round(cy + h / 2)))


def enhance_slot_button(index):
    """
    Args:
        index (int): Material slot index, row major

    Returns:
        Button: Clickable centre of that material card
    """
    area = enhance_slot_area(index)
    return Button(area=area, color=(), button=area, name=f'ENHANCE_SLOT_{index}')


def enhance_slot_index(area):
    """
    Args:
        area (tuple): Area of a matched material card portrait

    Returns:
        int: Material slot index that area belongs to
        None: If the area is not on the material slot grid
    """
    center = ((area[0] + area[2]) / 2, (area[1] + area[3]) / 2)
    nearest = min(range(ENHANCE_SLOT_COUNT),
                  key=lambda index: (enhance_slot_center(index)[0] - center[0]) ** 2
                                    + (enhance_slot_center(index)[1] - center[1]) ** 2)
    cx, cy = enhance_slot_center(nearest)
    if ((cx - center[0]) ** 2 + (cy - center[1]) ** 2) ** 0.5 > max(ENHANCE_SLOT_PITCH) / 2:
        return None
    return nearest


class Enhancement(Dock):
    @property
    def _retire_amount(self):
        if self.config.Retirement_RetireMode == 'one_click_retire':
            return 3000
        if self.config.Retirement_RetireMode == 'old_retire':
            if self.config.OldRetire_RetireAmount == 'retire_all':
                return 3000
            if self.config.OldRetire_RetireAmount == 'retire_10':
                return 10
        return 3000

    @property
    def _retire_keep_common_cv(self):
        """
        Returns:
            str: "any" or specific ship name, or empty string if GemsFarming is not enabled
        """
        if not self.config.is_task_enabled('GemsFarming'):
            return ''
        return self.config.cross_get('GemsFarming.GemsFarming.CommonCV', default='any')

    def _enhance_enter(self, favourite=False, ship_type=None):
        """
        Pages:
            in: page_dock
            out: page_ship_enhance

        Returns:
            bool: False with filter applied resulting
                  in empty dock.
                  Otherwise true with at least 1 card
                  available to be picked.
        """
        if favourite:
            self.dock_favourite_set(enable=True, wait_loading=False)

        if ship_type is not None:
            ship_type = str(ship_type)
            self.dock_filter_set(extra='enhanceable', index=ship_type)
        else:
            self.dock_filter_set(extra='enhanceable')

        if self.appear(DOCK_EMPTY, offset=(30, 30)):
            return False

        return self.dock_enter_first()

    def _enhance_quit(self):
        """
        Pages:
            in: page_ship_enhance
            out: page_dock
        """
        self.ui_back(DOCK_CHECK)
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set()

    def _enhance_confirm(self, skip_first_screenshot=True):
        """
        Pages:
            in: EQUIP_CONFIRM
            out: page_ship_enhance, without info_bar
        """

        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear(GET_ITEMS_1, interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                self.interval_reset(ENHANCE_CONFIRM)
                confirm_timer.reset()
                continue

            # End
            if self.appear(ENHANCE_CONFIRM, offset=(30, 30)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _enhance_get_deselect_cv(self, first_slot=False):
        """
        Args:
            first_slot: True to check in first slot only, False to check in all slots

        Returns:
            Button | None: Button of common rarity CV to de-select, or None if not found
        """
        cv = self._retire_keep_common_cv
        if not cv:
            return None
        dict_template = {
            'bogue': TEMPLATE_ENHANCE_BOGUE,
            'hermes': TEMPLATE_ENHANCE_HERMES,
            'langley': TEMPLATE_ENHANCE_LANGLEY,
            'ranger': TEMPLATE_ENHANCE_RANGER,
        }
        if cv != 'any':
            dict_template = {cv: dict_template[cv]}

        if first_slot:
            # outer pad 22 px reaches slot edge
            area = area_pad(EMPTY_ENHANCE_SLOT_PLUS.area, pad=-22)
        else:
            area = ENHANCE_AREA_FULL.area
        image = self.image_crop(area, copy=False)

        for cv, template in dict_template.items():
            sim, button = template.match_result(image)
            if sim > 0.85:
                button = button.move(area[:2])
                return Button(area=button.area, color=button.color, button=button.area,
                              name=f'TEMPLATE_ENHANCE_{cv.upper()}_RETIRE')

        return None

    def _enhance_slot_empty(self, index):
        """
        Args:
            index (int): Material slot index, row major

        Returns:
            bool: If that material slot currently shows the empty slot '+'
        """
        cx, cy = enhance_slot_center(index)
        area = EMPTY_ENHANCE_SLOT_PLUS.area
        dx = int(round(cx - (area[0] + area[2]) / 2))
        dy = int(round(cy - (area[1] + area[3]) / 2))
        offset = (dx - ENHANCE_SLOT_MATCH_OFFSET, dy - ENHANCE_SLOT_MATCH_OFFSET,
                  dx + ENHANCE_SLOT_MATCH_OFFSET, dy + ENHANCE_SLOT_MATCH_OFFSET)
        return EMPTY_ENHANCE_SLOT_PLUS.match(
            self.device.image, offset=offset, similarity=ENHANCE_SLOT_MATCH_SIMILARITY)

    def _enhance_selection_page(self):
        """
        Returns:
            bool: If the material-selection list is open
        """
        return self.appear(ENHANCE_SELECT_CANCEL, threshold=30) \
            and self.appear(ENHANCE_SELECT_CONFIRM, threshold=30)

    def handle_enhance_selection_page(self):
        """
        Close the material-selection list (选择强化材料, 已选中 N/12), which a click
        on an empty material slot opens.  It carries no ENHANCE_RECOMMEND, so no
        other state of _enhance_choose() can leave it and the state machine would
        spin on it until the 60s stuck check.

        Pages:
            in: material-selection list
            out: page_ship_enhance

        Returns:
            bool: If the page appeared
        """
        if not self._enhance_selection_page():
            return False

        logger.info('Enhance material selection list is open, cancelling it')
        self.interval_clear(ENHANCE_SELECT_CANCEL)
        for _ in self.loop(timeout=5):
            if not self._enhance_selection_page():
                break
            if self.appear_then_click(ENHANCE_SELECT_CANCEL, threshold=30, interval=1):
                continue
        else:
            logger.warning('Enhance material selection list did not close')

        if self._enhance_selection_page():
            raise GameStuckError('Enhance material selection list cannot be cancelled')
        return True

    def _enhance_deselect_cv(self):
        """
        De-select common rarity CV from enhance material slots

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance
        """
        cv = self._enhance_get_deselect_cv()
        if cv is None:
            return

        slot = enhance_slot_index(cv.area)
        if slot is None:
            logger.warning(f'Enhance de-select common CV: no material slot at {cv.area}')
            return

        logger.info(f'Enhance de-select common CV')
        self.interval_clear(ENHANCE_RECOMMEND, interval=2)
        EMPTY_ENHANCE_SLOT_PLUS.ensure_template()

        # Both the click and the exit test are anchored on the slot cell the
        # portrait matched in, not on the portrait match itself.  The templates
        # are 42x18 / 42x22 crops of the ship's eye region, which is not centred
        # in the 82x82 cell, so a box around the match clips the '+' that the game
        # draws at the cell centre: replayed on archived frames the old test
        # needed the match within ~21 px of the centre and returned 0.47 instead
        # of 0.91 beyond that.  A missed de-select then re-clicked the same spot,
        # which is the empty slot's '+' once the material is gone; that click
        # opens the material-selection list, and 12 runs between 2026-09-09 and
        # 2026-09-27 died there on the 60s stuck check.
        clicked = 0
        click_timer = Timer(ENHANCE_DESELECT_CLICK_INTERVAL, count=1).start()
        for _ in self.loop():
            # Upstream handles entering the dock after an already empty slot is
            # clicked; normalize that page before testing the material cell.
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                logger.info('Enhance de-select entered dock')
                self._enhance_exit_dock()
                logger.info('Enhance de-select common CV done (exit from dock)')
                break
            if self._enhance_slot_empty(slot):
                logger.info(f'Enhance de-select common CV done')
                break

            # Click only while that cell still holds the common CV: clicking an
            # empty slot opens the material-selection list.
            located = self._enhance_get_deselect_cv()
            if located is None:
                logger.info('Enhance de-select common CV done, no common CV material left')
                break
            if enhance_slot_index(located.area) != slot:
                logger.info('Enhance de-select common CV done, common CV is not in that slot anymore')
                break
            if clicked >= ENHANCE_DESELECT_MAX_CLICK:
                logger.warning('Enhance de-select common CV failed, material still selected')
                break
            if click_timer.reached():
                self.device.click(enhance_slot_button(slot))
                clicked += 1
                click_timer.reset()

    def _enhance_exit_dock(self):
        for _ in self.loop():
            if self.appear(ENHANCE_RECOMMEND, offset=(5, 5)):
                break
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                logger.info(f'{DOCK_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue

    def _enhance_choose(self, ship_count, skip_first_screenshot=True):
        """
        Refactor the implementation.
        Divided the enhancement process into
        several state functions. Use a DFA method
        to call those functions according to
        current state. Each state corresponds to
        a function with the same name.

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance

        Args:
            ship_count (int): ship_count, must be
            non-zero positive integer

        Returns:
            True if able to enhance otherwise False
            Always paired with current ship_count
        """
        need_to_skip: bool = False

        def state_enhance_check():
            # Check the base case, switch to ready if enhancement can continue
            nonlocal need_to_skip
            need_to_skip = False
            if ship_count <= 0:
                logger.info(
                    'Reached maximum number to check, exiting current category')
                return "state_enhance_exit"
            if not self.ship_side_navbar_ensure(bottom=4):
                return "state_enhance_check"

            self.wait_until_appear(ENHANCE_RECOMMEND, offset=(
                5, 5), skip_first_screenshot=True)
            return "state_enhance_ready"

        def state_enhance_ready():
            # Wait until ENHANCE_RECOMMEND appears
            if self.appear_then_click(ENHANCE_RECOMMEND, offset=(5, 5), interval=0.3):
                logger.info('Set enhancement material by recommendation.')
                return "state_enhance_recommend"

            return "state_enhance_ready"

        def state_enhance_recommend():
            # The material-selection list can be left open by a click on an empty
            # material slot; close it before judging the slots, nothing else in
            # this state machine can leave that page.
            if self.handle_enhance_selection_page():
                return "state_enhance_recommend"

            # Judge if enhance material appeared
            if not EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(20, 20)):
                if self._retire_keep_common_cv:
                    # consider empty if first slot is common CV and second slot is empty
                    # to avoid infinite loop of recommend and de-select
                    # the second slot is 92px to the left
                    if EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(72, -20, 112, 20)) \
                            and self._enhance_get_deselect_cv(first_slot=True):
                        logger.info('Only 1 common CV material, consider as no material found as enhancement')
                        logger.info('Enhancement failed. Swiping to next ship if feasible')
                        return "state_enhance_fail"
                    # de-select common CV
                    self._enhance_deselect_cv()

                logger.info('Material found. Try enhancing...')
                return "state_enhance_attempt"
            elif self.info_bar_count():
                logger.info('No material found for enhancement.')
                logger.info('Enhancement failed. Swiping to next ship if feasible')
                return "state_enhance_fail"

            return "state_enhance_ready"

        def state_enhance_attempt():
            # Wait until ENHANCE_CONFIRM appears
            if (self.appear_then_click(ENHANCE_CONFIRM, offset=(5, 5), interval=0.3)
                    or self.appear(EQUIP_CONFIRM, offset=(30, 30))
                    or self.info_bar_count()
                    or self.handle_popup_confirm('ENHANCE')):
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_confirm():
            # Succeeded if EQUIP_CONFIRM appeared, otherwise failed
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                logger.info('Enhancement Successful')
                self._enhance_confirm()
                return "state_enhance_success"
            elif self.info_bar_count():
                logger.info(
                    'Enhancement impossible, ship currently in battle. Swiping to next ship if feasible')
                nonlocal need_to_skip
                need_to_skip = True
                return "state_enhance_fail"
            elif self.handle_popup_confirm('ENHANCE'):
                logger.info('Trying a temporary ship')
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_fail():
            # Avoid a misjudgement caused by broken network
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                return "state_enhance_confirm"

            # Try to swipe to next
            if self.ship_view_next(check_button=ENHANCE_RECOMMEND):
                if not need_to_skip:
                    nonlocal ship_count
                    ship_count -= 1
                return "state_enhance_check"
            else:
                # Avoid a misjudgement caused by broken network
                if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                    return "state_enhance_confirm"
                else:
                    logger.info('Swiped failed, exiting current category')
                    return "state_enhance_exit"

        def state_enhance_success():
            return True

        def state_enhance_exit():
            return False

        state = "state_enhance_check"
        state_list = []
        while isinstance(state, str):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            logger.info(f'Call state function: {state}')

            if state == "state_enhance_check":
                # Avoid too_many_click exception caused by multiple tries without material
                if state_list[-2:] == ["state_enhance_recommend", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'SHIP_SWIPE']):
                        self.device.click_record.pop()
                # Avoid too_many_click exception caused by enhancement failure on in-battle ships
                elif state_list[-3:] == ["state_enhance_attempt", "state_enhance_confirm", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'SHIP_SWIPE', 'ENHANCE_CONFIRM']):
                        self.device.click_record.pop()
                state_list.clear()
            state_list.append(state)
            if len(state_list) > 30:
                logger.critical(f'Too many state transitions: {state_list}')
                raise GameStuckError('Too many state transitions')

            try:
                state = locals()[state]()
            except KeyError as e:
                logger.warning(f'Unknown state function: {state}')
                raise ScriptError(f'Unknown state function: {state}')

        return state, ship_count

    def enhance_ships(self, favourite=None):
        """
        Enhance target ships by specified order
        of types listed in ENHANCE_ORDER_STRING

        Invalid types are treated as requesting
        from ALAS to choose a valid one at random

        Pages:
            in: page_dock
            out: page_dock

        Args:
            favourite (bool):

        Returns:
            int: total enhanced
        """
        if favourite is None:
            favourite = self.config.Enhance_ShipToEnhance == 'favourite'

        logger.hr('Enhancement by type')
        total = 0

        # Process ENHANCE_ORDER_STRING if any into ship_types
        if self.config.Enhance_Filter is not None:
            ship_types = [s.strip().lower()
                          for s in self.config.Enhance_Filter.split('>')]
            ship_types = list(filter(''.__ne__, ship_types))
            if len(ship_types) == 0:
                ship_types = [None]
        else:
            ship_types = [None]
        logger.attr('Enhance Order', ship_types)

        # Process available ship types for choice randomization
        # Removing types that have already been specified by
        # ENHANCE_ORDER_STRING
        available_ship_types = VALID_SHIP_TYPES.copy()
        [available_ship_types.remove(s)
         for s in ship_types if s in available_ship_types]

        for ship_type in ship_types:
            # None check, do not execute if is None
            # Otherwise, select a type at random since
            # user has specified an unrecognized type
            if ship_type is not None and ship_type not in VALID_SHIP_TYPES:
                if len(available_ship_types) == 0:
                    logger.info(
                        'No more ship types for ALAS to choose from, skipping iteration')
                    continue
                ship_type = choice(available_ship_types)
                available_ship_types.remove(ship_type)

            logger.info(f'Favourite={favourite}, Ship Type={ship_type}')

            # Continue if at least 1 CARD_GRID is selectable
            # otherwise skip to next ship type
            if not self._enhance_enter(favourite=favourite, ship_type=ship_type):
                logger.hr(f'Dock Empty by ship type {ship_type}')
                continue

            current_count = self.config.Enhance_CheckPerCategory
            while 1:
                choose_result, current_count = self._enhance_choose(
                    ship_count=current_count)
                if not choose_result:
                    break
                total += 10
                if total >= self._retire_amount:
                    break
            self.ui_back(DOCK_CHECK)

        self._enhance_quit()
        return total

    def _enhance_handler(self):
        """
        Pages:
            in: RETIRE_APPEAR
            out:

        Returns:
            tuple(int, int): (enhance turn count, remaining dock amount)

        Pages:
            in: DOCK_CHECK
            out: the page before retirement popup
        """
        total = self.enhance_ships()
        _, remain, _ = OCR_DOCK_AMOUNT.ocr(self.device.image)

        self.dock_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total, remain
