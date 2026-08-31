from datetime import datetime

from module.config.utils import get_os_next_reset, get_os_reset_remain
from module.logger import logger
from module.os.cl1 import get_cl1_yellow_coins_preserve
from module.os.config import OSConfig
from module.os.map_operation import OSMapOperation
from module.os.operation_siren import OperationSiren
from module.os.tasks.cross_month import (
    is_cross_month_catch_up,
    monthly_shop_clearout_start,
)
from module.os_handler.action_point import ActionPointLimit


class OSCampaignRun(OSMapOperation):
    def load_campaign(self, cls=OperationSiren, skip_first_auto_search=False):
        config = self.config.merge(OSConfig())
        campaign = cls(config=config, device=self.device)
        campaign.os_init(skip_first_auto_search=skip_first_auto_search)
        return campaign

    def _route_high_value_task_to_priority_dispatch(self):
        if self.config.OpsiMeowfficerFarming_OperatingMode != 'hazard1_mode':
            return False

        logger.info(f'Route {self.config.task.command} through unified CL1 priority dispatch')
        with self.config.multi_set():
            self.config.task_delay(success=True)
            self.config.cross_set(
                keys=f'{self.config.task.command}.Scheduler.Enable',
                value=False,
            )
            self.config.task_call('OpsiMeowfficerFarming')
        return True

    def opsi_explore(self):
        try:
            campaign = self.load_campaign()
            campaign.os_explore()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_shop(self):
        try:
            campaign = self.load_campaign()
            campaign.os_shop()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_voucher(self):
        try:
            campaign = self.load_campaign()
            campaign.os_voucher()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_daily(self):
        try:
            campaign = self.load_campaign()
            campaign.os_daily()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_meowfficer_farming(self):
        try:
            campaign = self.load_campaign()
            campaign.os_meowfficer_farming_priority()
        except ActionPointLimit:
            if get_os_reset_remain() > 0:
                self.config.task_delay(server_update=True)
                self.config.task_call('Reward')
                if self.config.is_task_enabled('OpsiHazard1Leveling'):
                    yellow_coins = self.get_yellow_coins()
                    yellow_coins_preserve = get_cl1_yellow_coins_preserve(self.config)
                    if yellow_coins > yellow_coins_preserve:
                        logger.info('OpsiMeowfficerFarming reached AP preserve, call OpsiHazard1Leveling back')
                        self.config.task_call('OpsiHazard1Leveling')
                    else:
                        logger.info(f'OpsiHazard1Leveling not called back because yellow coins {yellow_coins} '
                                    f'<= preserve {yellow_coins_preserve}')
            else:
                logger.info('Just less than 1 day to OpSi reset, delay 2.5 hours')
                self.config.task_delay(minute=150, server_update=True)

    def opsi_hazard1_leveling(self):
        try:
            campaign = self.load_campaign()
            campaign.os_hazard1_leveling()
        except ActionPointLimit:
            self.config.task_delay(minute=60)

    def opsi_obscure(self):
        if self._route_high_value_task_to_priority_dispatch():
            return
        try:
            campaign = self.load_campaign()
            campaign.os_obscure()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)
            if self.config.is_task_enabled('OpsiHazard1Leveling') \
                    and self.get_yellow_coins() > self.config.OS_CL1_YELLOW_COINS_PRESERVE:
                self.config.task_call('OpsiHazard1Leveling')           

    def opsi_month_boss(self):
        if self.config.SERVER in ['tw']:
            logger.info(f'OpsiMonthBoss is not supported in {self.config.SERVER},'
                        ' please contact server maintainers')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
            return
        try:
            campaign = self.load_campaign()
            campaign.clear_month_boss()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_abyssal(self):
        if self._route_high_value_task_to_priority_dispatch():
            return
        try:
            campaign = self.load_campaign()
            campaign.os_abyssal()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)
            if self.config.is_task_enabled('OpsiHazard1Leveling') \
                    and self.get_yellow_coins() > self.config.OS_CL1_YELLOW_COINS_PRESERVE:
                self.config.task_call('OpsiHazard1Leveling')

    def opsi_archive(self):
        try:
            campaign = self.load_campaign()
            campaign.os_archive()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)

    def opsi_stronghold(self):
        if self._route_high_value_task_to_priority_dispatch():
            return
        try:
            campaign = self.load_campaign()
            campaign.os_stronghold()
        except ActionPointLimit:
            self.config.opsi_task_delay(ap_limit=True)
            if self.config.is_task_enabled('OpsiHazard1Leveling') \
                    and self.get_yellow_coins() > self.config.OS_CL1_YELLOW_COINS_PRESERVE:
                self.config.task_call('OpsiHazard1Leveling')

    def opsi_cross_month(self):
        catch_up = is_cross_month_catch_up(self.config.task.next_run, datetime.now())
        if catch_up:
            # os_init() enters OpSi from other pages and would refresh the world.
            # An overdue run is safe only if the client is already inside it.
            self.device.screenshot()
            if not (self.is_in_map() or self.is_in_globe()):
                logger.warning(
                    'Overdue OpsiCrossMonth found outside Operation Siren; '
                    'the old instance is no longer safely reachable, skip it'
                )
                self.config.task_delay(
                    target=monthly_shop_clearout_start(get_os_next_reset())
                )
                self.config.task_stop()
                return
        campaign = self.load_campaign(skip_first_auto_search=catch_up)
        try:
            campaign.os_cross_month(catch_up=catch_up)
        except ActionPointLimit:
            campaign.os_cross_month_end()
