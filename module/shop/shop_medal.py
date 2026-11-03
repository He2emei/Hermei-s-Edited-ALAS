import numbers

import cv2
import numpy as np
from scipy import signal

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.map_detection.utils import Points
from module.ocr.ocr import Digit, DigitYuv, Ocr
from module.shop.assets import *
from module.shop.base import ShopItemGrid_250814
from module.shop.clerk import OCR_SHOP_AMOUNT, OCR_SHOP_SELECT_STOCK, ShopClerk
from module.shop.medal_monthly_ledger import MedalMonthlyLedger
from module.shop.medal_monthly_policy import balanced_choice, priority as medal_monthly_priority
from module.shop.shop_select_globals import SELECT_ITEM_INFO_MAP
from module.shop.shop_status import ShopStatus
from module.ui.scroll import Scroll


class ShopScroll(Scroll):
    def match_color(self, main):
        background_transparency = 0.2
        button_transparency = 0.5
        delta_x = 3
        area = (
            self.area[0] - delta_x,
            self.area[1],
            self.area[2] + delta_x,
            self.area[3]
        )
        image = main.image_crop(area, copy=False).astype(np.float32)
        baseline_color = np.mean(image[:, [0, -1], :], axis=1)
        masked_color = image[:, image.shape[1] // 2, :]
        background_mask = background_transparency * np.array(self.color) + (1 - background_transparency) * baseline_color
        button_mask = button_transparency * np.array(self.color) + (1 - button_transparency) * baseline_color
        err_background = np.sum((masked_color - background_mask) ** 2, axis=1)
        err_button = np.sum((masked_color - button_mask) ** 2, axis=1)
        mask = err_button < err_background
        self.length = np.sum(mask)
        return mask


MEDAL_SHOP_SCROLL_250814 = ShopScroll(
    MEDAL_SHOP_SCROLL_AREA_250814.button,
    color=(44, 48, 56),
    name="MEDAL_SHOP_SCROLL_250814"
)
MEDAL_SHOP_SCROLL_250814.drag_threshold = 0.1
# A little bit larger than 0.1 to handle bottom
MEDAL_SHOP_SCROLL_250814.edge_threshold = 0.12


class ShopPriceOcr(DigitYuv):
    def after_process(self, result):
        result = Ocr.after_process(self, result)
        # '100' detected as '00' on retrofit blueprint
        if result == '00':
            result = '100'
        return Digit.after_process(self, result)


PRICE_OCR = ShopPriceOcr([], letter=(255, 223, 57), threshold=32, name='Price_ocr')
if server.server == 'jp':
    PRICE_OCR_250814 = Digit([], lang='cnocr', letter=(235, 235, 255), threshold=128, name='Price_ocr')
else:
    PRICE_OCR_250814 = Digit([], letter=(255, 255, 255), threshold=128, name='Price_ocr')
TEMPLATE_MEDAL_ICON = Template('./assets/shop/cost/Medal.png')
TEMPLATE_MEDAL_ICON_2 = Template('./assets/shop/cost/Medal_2.png')
TEMPLATE_MEDAL_ICON_3 = Template('./assets/shop/cost/Medal_3.png')


class MedalShop2_250814(ShopClerk, ShopStatus):
    MONTHLY_CLEAR_FILTER = 'MonthlyClear'
    MONTHLY_CLEAR_MAX_PAGES_PER_RANK = 12

    @cached_property
    def shop_filter(self):
        """
        Returns:
            str:
        """
        return self.config.MedalShop2_Filter.strip()

    # New UI in 2025-08-14
    def _get_medals(self):
        """
        Returns:
            np.array: [[x1, y1], [x2, y2]], location of the medal icon upper-left corner.
        """
        area = (265, 317, 999, 635)
        # copy image because we gonna paint it
        image = self.image_crop(area, copy=True)
        medals = TEMPLATE_MEDAL_ICON_3.match_multi(image, similarity=0.5, threshold=5)
        medals = Points([(0., m.area[1]) for m in medals]).group(threshold=5)
        logger.attr('Medals_icon', len(medals))
        return medals

    def wait_until_medal_appear(self, skip_first_screenshot=True):
        """
        After entering medal shop page,
        items are not loaded that fast,
        wait until any medal icon appears
        """
        timeout = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            medals = self._get_medals()

            if timeout.reached():
                break
            if len(medals):
                break

    @cached_property
    def shop_grid(self):
        return self.shop_medal_grid()

    def shop_medal_grid(self):
        """
        Returns:
            ButtonGrid:
        """
        # (472, 348, 1170, 648)
        medals = self._get_medals()
        count = len(medals)
        if count == 0:
            logger.warning('Unable to find medal icon, assume item list is at top')
            origin_y = 228
            delta_y = 223
            row = 2
        elif count == 1:
            y_list = medals[:, 1]
            # +256, top of the crop area in _get_medals()
            # -125, from the top of medal icon to the top of shop item
            origin_y = y_list[0] + 317 - 126
            delta_y = 223
            row = 1
        elif count == 2:
            y_list = medals[:, 1]
            y1, y2 = y_list[0], y_list[1]
            origin_y = min(y1, y2) + 317 - 126
            delta_y = abs(y1 - y2)
            row = 2
        else:
            logger.warning(f'Unexpected medal icon match result: {[m for m in medals]}')
            origin_y = 228
            delta_y = 223
            row = 2

        # Make up a ButtonGrid
        # Original grid is:
        # shop_grid = ButtonGrid(
        #     origin=(476, 246), delta=(156, 213), button_shape=(98, 98), grid_shape=(5, 2), name='SHOP_GRID')
        shop_grid = ButtonGrid(
            origin=(265, origin_y), delta=(169, delta_y), button_shape=(64, 64), grid_shape=(5, row), name='SHOP_GRID')
        return shop_grid

    shop_template_folder = './assets/shop/medal'

    @cached_property
    def shop_medal_items(self):
        """
        Returns:
            ShopItemGrid_250814:
        """
        shop_grid = self.shop_grid
        shop_medal_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            amount_area=(60, 74, 96, 95),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 122, 85, 149),
        )
        shop_medal_items.load_template_folder(self.shop_template_folder)
        shop_medal_items.load_cost_template_folder('./assets/shop/cost')
        shop_medal_items.similarity = 0.85  # Lower the threshold for consistent matches of PR/DRBP
        shop_medal_items.cost_similarity = 0.5
        shop_medal_items.price_ocr = PRICE_OCR_250814
        return shop_medal_items

    def shop_items(self) -> ShopItemGrid_250814:
        """
        Shared alias name for all shops,
        so to use  @Config must define
        a unique alias as cover
        Overriding to add type hint to
        accommodate unique func,
        get_soldout_count in run()

        Returns:
            ShopItemGrid_250814:
        """
        return self.shop_medal_items

    def shop_currency(self):
        """
        Ocr shop medal currency
        Then return medal count

        Returns:
            int: medal amount
        """
        self._currency = self.status_get_medal()
        logger.info(f'Medal: {self._currency}')
        return self._currency

    def _monthly_takeover(self, reason):
        raise RequestHumanTakeover('Monthly medal receipt: {}'.format(reason))

    def _monthly_load_state(self):
        try:
            state = self._monthly_ledger.load()
        except ValueError as exc:
            self._monthly_takeover('ledger is invalid: {}'.format(exc))
        if state['pending'] is not None:
            self._monthly_takeover('an earlier purchase is pending; manual verification is required')
        return state

    @staticmethod
    def _monthly_integer(value, label, allow_zero=True):
        if (isinstance(value, bool) or not isinstance(value, numbers.Integral)
                or value < (0 if allow_zero else 1)):
            raise RequestHumanTakeover('Monthly medal receipt: invalid {}'.format(label))
        return int(value)

    def _monthly_require_shop_page(self):
        if (not isinstance(self.device.image, np.ndarray)
                or self.device.image.shape[:2] != (720, 1280)
                or not self.match_template_color(TAB_MEDAL, offset=(20, 20))
                or not self.match_template_color(NAV_MONTHLY, offset=(20, 20))):
            self._monthly_takeover('the selected monthly medal page is not confirmed')

    def _monthly_stable_currency(self, allow_zero=False):
        self._monthly_require_shop_page()
        first = self.status_get_medal()
        self.device.screenshot()
        self._monthly_require_shop_page()
        second = self.status_get_medal()
        first = self._monthly_integer(first, 'first currency reading', allow_zero=allow_zero)
        second = self._monthly_integer(second, 'second currency reading', allow_zero=allow_zero)
        if first != second:
            self._monthly_takeover('currency did not match across two frames')
        return first

    def _monthly_stable_select_stock(self):
        first = OCR_SHOP_SELECT_STOCK.ocr(self.device.image)
        self.device.screenshot()
        second = OCR_SHOP_SELECT_STOCK.ocr(self.device.image)
        if (not isinstance(first, (list, tuple)) or len(first) != 3
                or not isinstance(second, (list, tuple)) or len(second) != 3):
            self._monthly_takeover('selection stock could not be read')
        first = tuple(self._monthly_integer(value, 'selection stock') for value in first)
        second = tuple(self._monthly_integer(value, 'selection stock') for value in second)
        if first != second:
            self._monthly_takeover('selection stock did not match across two frames')
        return first

    def _monthly_stable_amount(self):
        first = OCR_SHOP_AMOUNT.ocr(self.device.image)
        self.device.screenshot()
        second = OCR_SHOP_AMOUNT.ocr(self.device.image)
        first = self._monthly_integer(first, 'selected amount', allow_zero=False)
        second = self._monthly_integer(second, 'selected amount', allow_zero=False)
        if first != second:
            self._monthly_takeover('selected amount did not match across two frames')
        return first

    def _monthly_family(self, item):
        if item.group == 'retrofit' and item.tier == 't3':
            return 'RetrofitT3'
        if item.group == 'plate' and item.tier == 't1':
            return 'PlateT1'
        return None

    @staticmethod
    def _monthly_choice_button(group, choice):
        item_info = SELECT_ITEM_INFO_MAP.get(group)
        if item_info is None or choice not in item_info['choices']:
            raise RequestHumanTakeover('Monthly medal receipt: no selector mapping for {} {}'.format(group, choice))
        return item_info['grid'].buttons[item_info['choices'][choice]]

    def shop_select_plan(self, item, stock_counter):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_select_plan(item, stock_counter)
        if getattr(self, '_monthly_current_item', None) is not item:
            self._monthly_takeover('selection is outside the active purchase')
        self._monthly_load_state()
        if not isinstance(stock_counter, (tuple, list)) or len(stock_counter) != 3:
            self._monthly_takeover('selection stock could not be read')
        counter = tuple(self._monthly_integer(v, 'selector stock') for v in stock_counter)
        if counter[1] != 0 or counter[0] != counter[2]:
            self._monthly_takeover('selector already has an unverified selection; cancel before retry')
        stock = counter[0]
        before = self._monthly_integer(getattr(self, '_monthly_before', None), 'pre-purchase balance', False)
        price = self._monthly_item_price(item)
        affordable = before // price
        family = self._monthly_family(item)

        if family is not None:
            choice_sets = {
                'RetrofitT3': ('dd', 'cl', 'bb', 'cv'),
                'PlateT1': ('general', 'gun', 'torpedo', 'antiair', 'plane'),
            }
            counts = self._monthly_load_state()['counts'][family]
            choice, quantity = balanced_choice(stock, affordable, choice_sets[family], counts)
            if choice is None:
                self._monthly_takeover('no available selection quantity')
            button = self._monthly_choice_button(item.group, choice)
        else:
            quantity = min(stock, affordable)
            if item.group == 'plate':
                button = self._monthly_choice_button('plate', 'general')
            elif item.group == 'retrofit' and item.tier == 't2':
                button = self._monthly_choice_button('retrofit', 'cl')
            else:
                choice = None
                button = self.shop_get_select(item)
            choice = None

        if quantity <= 0:
            self._monthly_takeover('no affordable selector stock')
        self._monthly_plan = {
            'item': item,
            'quantity': int(quantity),
            'choice': choice if family is not None else None,
            'family': family,
        }
        return button, int(quantity)

    @staticmethod
    def _monthly_item_price(item):
        price = getattr(item, 'price', None)
        if (getattr(item, 'cost', None) != 'Medal'
                or not isinstance(price, numbers.Integral) or isinstance(price, bool) or price <= 0):
            raise RequestHumanTakeover('Monthly medal receipt: item cost or price is invalid')
        return int(price)

    def _monthly_prepare(self, item, quantity, choice=None, family=None):
        if getattr(self, '_monthly_current_item', None) is not item:
            self._monthly_takeover('confirmation is outside the active purchase')
        if getattr(self, '_monthly_receipt', None) is not None:
            self._monthly_takeover('confirmation was already prepared; refusing a second click')
        if medal_monthly_priority(getattr(item, 'name', None)) is None:
            self._monthly_takeover('item is unknown or protected')
        quantity = self._monthly_integer(quantity, 'purchase quantity', allow_zero=False)
        price = self._monthly_item_price(item)
        before = self._monthly_integer(getattr(self, '_monthly_before', None), 'pre-purchase balance', False)
        if before < quantity * price:
            self._monthly_takeover('recorded balance cannot cover the selected quantity')
        self._monthly_load_state()
        try:
            self._monthly_receipt = self._monthly_ledger.prepare(
                item.name, choice, quantity, price, before, family=family)
        except ValueError as exc:
            self._monthly_takeover('could not persist purchase receipt: {}'.format(exc))

    def shop_before_select_confirm(self, item, limit):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_before_select_confirm(item, limit)
        plan = getattr(self, '_monthly_plan', None)
        if not isinstance(plan, dict) or plan.get('item') is not item or plan.get('quantity') != limit:
            self._monthly_takeover('selector quantity does not match its plan')
        _, remain, _ = self._monthly_stable_select_stock()
        if remain != limit:
            self._monthly_takeover('selector remaining count does not match the selected quantity')
        self._monthly_prepare(item, limit, plan['choice'], plan['family'])

    def shop_before_amount_confirm(self, item, limit):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_before_amount_confirm(item, limit)
        if self._monthly_stable_amount() != limit:
            self._monthly_takeover('amount does not match the selected quantity')
        self._monthly_prepare(item, limit)

    def shop_before_single_confirm(self, item):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_before_single_confirm(item)
        self._monthly_prepare(item, 1)

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_buy_execute(item, skip_first_screenshot=skip_first_screenshot)
        self._monthly_current_item = item
        self._monthly_before = None
        self._monthly_receipt = None
        self._monthly_plan = None
        try:
            self._monthly_before = self._monthly_stable_currency(allow_zero=False)
            self._currency = self._monthly_before
            super().shop_buy_execute(item, skip_first_screenshot=skip_first_screenshot)
            receipt = self._monthly_receipt
            if receipt is None:
                self._monthly_takeover('purchase ended without a durable confirmation receipt')
            after = self._monthly_stable_currency(allow_zero=True)
            try:
                return self._monthly_ledger.commit(receipt['txid'], after)
            except ValueError as exc:
                self._monthly_takeover('currency debit did not verify the receipt: {}'.format(exc))
        finally:
            self._monthly_current_item = None
            self._monthly_before = None
            self._monthly_receipt = None
            self._monthly_plan = None

    def _monthly_clear_startup(self):
        try:
            self._monthly_ledger = MedalMonthlyLedger('.', getattr(self.config, 'config_name', None))
            state = self._monthly_ledger.load()
        except ValueError as exc:
            self._monthly_takeover('profile or ledger is invalid: {}'.format(exc))
        if state['pending'] is not None:
            self._monthly_takeover('an earlier purchase is pending; manual verification is required')

    def shop_has_loaded(self, items):
        """
        If any item parsed with a default
        price of 5000; then shop cannot
        be safely bought from yet

        Returns:
            bool
        """
        for item in items:
            if int(item.price) == 5000:
                return False
        return True

    def shop_interval_clear(self):
        """
        Clear interval on select assets for
        shop_buy_handle
        """
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_SELECT)
        self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)

    def shop_buy_handle(self, item):
        """
        Handle shop_medal buy interface if detected

        Args:
            item: Item to handle

        Returns:
            bool: whether interface was detected and handled
        """
        if self.appear(SHOP_BUY_CONFIRM_SELECT, offset=(20, 20), interval=3):
            self.shop_buy_select_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_SELECT)
            return True
        if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
            self.shop_buy_amount_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
            return True

        return False

    def shop_check_custom_item(self, item):
        # MonthlyClear never delegates to custom item handling, which could
        # bypass the known-name and protected-ship checks.
        if self.shop_filter == self.MONTHLY_CLEAR_FILTER:
            return False
        return super().shop_check_custom_item(item)

    def _monthly_blueprint_frame_rank(self, item, image):
        # The live generic PR and DR boxes both match the old DRS5 template.
        # Their rarity corners are independent of the ALL blueprint artwork.
        x, y, _, _ = (int(v) for v in item.button)
        if image.shape[:2] != (720, 1280) or not (51 <= x <= 1158 and 0 <= y <= 610):
            return None
        title = str(Ocr([(x - 51, y + 70, x + 120, y + 103)], lang='cnocr',
                        letter=(60, 75, 80), threshold=128,
                        name='MedalBlueprintTitle').ocr(image)).replace(' ', '')
        if '定向' not in title:
            return None
        red, green, blue = image[y + 3:y + 8, x + 3:x + 8].mean(axis=(0, 1))
        if blue - red > 45 and green - red > 45:
            return 3
        if red - blue > 45 and green - blue > 35 and red > 150:
            return 9
        return None

    def _monthly_item_rank(self, item):
        rank = medal_monthly_priority(getattr(item, 'name', None))
        if rank not in (3, 9):
            return rank
        if getattr(self, '_monthly_clear_active_rank', None) not in (3, 9):
            return None
        first = self._monthly_blueprint_frame_rank(item, self.device.image)
        self.device.screenshot()
        second = self._monthly_blueprint_frame_rank(item, self.device.image)
        if first is None or first != second:
            self._monthly_clear_metadata_blocked = True
            logger.warning('MonthlyClear blueprint rarity could not be verified twice; lower ranks blocked')
            return None
        return first

    def shop_get_item_to_buy(self, items):
        if self.shop_filter != self.MONTHLY_CLEAR_FILTER:
            return super().shop_get_item_to_buy(items)

        rank = getattr(self, '_monthly_clear_active_rank', None)
        if rank is None:
            return None

        for item in items:
            item_rank = self._monthly_item_rank(item)
            if item_rank != rank:
                continue

            price = getattr(item, 'price', None)
            valid_price = isinstance(price, numbers.Integral) and not isinstance(price, bool) and price > 0
            if getattr(item, 'cost', None) != 'Medal' or not valid_price:
                self._monthly_clear_metadata_blocked = True
                logger.warning(f'MonthlyClear rank {rank}: unreadable item cost/price for {item.name}; '
                               'lower ranks will remain blocked')
                continue

            price = int(price)
            if price > self._currency:
                self._monthly_clear_budget_blocked = True
                logger.info(f'MonthlyClear rank {rank}: {item.name} costs {price}, '
                            f'current Medal balance is {self._currency}')
                continue
            return item
        return None

    def _run_monthly_clear(self):
        """Scan the whole list once per rank so later pages keep priority."""
        import time

        self._monthly_clear_startup()
        scroll = MEDAL_SHOP_SCROLL_250814
        logger.hr('Medal Shop MonthlyClear', level=1)
        for rank in range(12):
            self._monthly_clear_active_rank = rank
            self._monthly_clear_budget_blocked = False
            self._monthly_clear_metadata_blocked = False

            before_top = scroll.cal_position(self)
            scroll.set_top(main=self)
            del_cached_property(self, 'shop_grid')
            del_cached_property(self, 'shop_medal_items')
            after_top = scroll.cal_position(self)
            if (np.isfinite(before_top) and np.isfinite(after_top)
                    and abs(after_top - before_top) >= scroll.drag_threshold):
                self.device.click_record_clear()
            time.sleep(0.5)

            if not scroll.at_top(self):
                logger.warning(f'MonthlyClear rank {rank}: could not verify list at top; stopping incomplete scan')
                break

            complete = False
            for page_index in range(self.MONTHLY_CLEAR_MAX_PAGES_PER_RANK):
                if self.shop_buy() is False:
                    logger.info(f'MonthlyClear rank {rank}: no Medal balance remains; lower ranks skipped')
                    self._monthly_clear_active_rank = None
                    return

                if scroll.at_bottom(self):
                    complete = True
                    break

                if page_index + 1 >= self.MONTHLY_CLEAR_MAX_PAGES_PER_RANK:
                    break
                before_page = scroll.cal_position(self)
                scroll.next_page(main=self, page=0.66)
                after_page = scroll.cal_position(self)
                del_cached_property(self, 'shop_grid')
                del_cached_property(self, 'shop_medal_items')

                moved = (np.isfinite(before_page) and np.isfinite(after_page)
                         and abs(after_page - before_page) >= scroll.drag_threshold)
                if moved:
                    self.device.click_record_clear()
                elif scroll.at_bottom(self):
                    complete = True
                    break
                else:
                    logger.warning(f'MonthlyClear rank {rank}: settled scroll made no measurable progress; '
                                   'stopping incomplete scan')
                    break

            if not complete:
                logger.warning(f'MonthlyClear rank {rank}: page bound reached or scan incomplete; '
                               'lower ranks skipped')
                break
            if self._monthly_clear_metadata_blocked:
                logger.warning(f'MonthlyClear rank {rank}: unreadable Medal cost/price; lower ranks skipped')
                break
            if self._monthly_clear_budget_blocked:
                logger.info(f'MonthlyClear rank {rank}: known items remain above current balance; '
                            'lower ranks skipped for insufficient Medal')
                break
            logger.info(f'MonthlyClear rank {rank}: scan complete')

        self._monthly_clear_active_rank = None

    def run(self):
        """
        Run Medal Shop
        """
        if self.shop_filter == self.MONTHLY_CLEAR_FILTER:
            return self._run_monthly_clear()

        # Base case; exit run if filter empty
        import time
        if not self.shop_filter:
            return

        # When called, expected to be in
        # correct Medal Shop interface
        logger.hr('Medal Shop', level=1)
        # Execute buy operations
        MEDAL_SHOP_SCROLL_250814.set_top(main=self)
        time.sleep(0.5)
        while 1:
            # sold items are auto sorted behind
            # if we find any soldout items, no need to check behind
            if self.shop_items().get_soldout_count(self.device.image):
                logger.info('Medal shop early stop')
                break

            self.shop_buy()

            if MEDAL_SHOP_SCROLL_250814.at_bottom(main=self):
                logger.info('Medal shop reach bottom, stop')
                break
            else:
                MEDAL_SHOP_SCROLL_250814.next_page(main=self, page=0.66)
                del_cached_property(self, 'shop_grid')
                del_cached_property(self, 'shop_medal_items')
                continue
