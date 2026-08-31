from datetime import datetime, timedelta

from module.config.utils import get_os_next_reset, get_server_next_update, get_os_reset_remain
from module.logger import logger
from module.os.map import OSMap
from module.os_handler.assets import EXCHANGE_CHECK, EXCHANGE_ENTER
from module.os_shop.assets import OS_SHOP_CHECK


class OpsiShop(OSMap):
    def _os_shop_visit(self, monthly_clearout=False, cross_month_action_points=False):
        """Visit the four port shops and buy items selected for this run."""
        if not self.zone.is_azur_port:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        self.port_enter()
        self.port_shop_enter()

        if self.appear(OS_SHOP_CHECK):
            if cross_month_action_points:
                needs_retry = self.handle_cross_month_port_supply_buy()
            elif monthly_clearout:
                needs_retry = self.handle_monthly_port_supply_buy()
            else:
                needs_retry = self.handle_port_supply_buy()
        else:
            logger.warning('There is no shop in the port.')
            needs_retry = None

        self.port_shop_quit()
        self.port_quit()
        return needs_retry

    def os_shop_monthly_clearout(self) -> bool:
        """
        Buy the fixed end-of-month item set from all four port shops.

        Returns:
            bool: True when selected items were seen, so another scan may be
                useful after purchases or when balances were insufficient.
        """
        logger.hr('OS port monthly clearout', level=1)
        result = self._os_shop_visit(monthly_clearout=True)
        # A missing shop page is not proof that all target items are gone.
        return True if result is None else result

    def os_shop_cross_month_action_points(self) -> bool:
        """Buy the large AP boxes after reset without leaving Operation Siren."""
        logger.hr('OS port cross-month action points', level=1)
        result = self._os_shop_visit(cross_month_action_points=True)
        return True if result is None else result

    def os_shop(self):
        """
        Buy all supplies in all ports.
        If not having enough yellow coins or purple coins, skip buying supplies in next port.
        """
        logger.hr('OS port daily', level=1)
        not_empty = self._os_shop_visit()
        if not_empty is None:
            next_reset = get_os_next_reset()
            logger.warning('There is no shop in the port, skip to the next month.')
            logger.attr('OpsiShopNextReset', next_reset)
        else:
            next_reset = self._os_shop_delay(not_empty)
            logger.info('OS port daily finished, delay to next reset')
            logger.attr('OpsiShopNextReset', next_reset)

        self.config.task_delay(target=next_reset)
        self.config.task_stop()

    def _os_shop_delay(self, not_empty) -> datetime:
        """
        Calculate the delay of OpsiShop.

        Args:
            not_empty (bool): Indicates whether the shop is not empty.

        Returns:
            datetime: The time of the next shop reset.
        """
        next_reset = None

        if not_empty:
            next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
        else:
            remain = get_os_reset_remain()
            next_reset = get_os_next_reset()
            if remain == 0:
                next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
            elif remain < 7:
                next_reset = next_reset - timedelta(days=1)
            else:
                next_reset = (
                    get_server_next_update(self.config.Scheduler_ServerUpdate) +
                    timedelta(days=6)
                )
        return next_reset
