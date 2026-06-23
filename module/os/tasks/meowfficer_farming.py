from module.config.utils import get_os_reset_remain
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.cl1 import get_cl1_yellow_coins_preserve
from module.os.map import OSMap


class OpsiMeowfficerFarming(OSMap):
    def os_meowfficer_farming(self):
        """
        Recommend 3 or 5 for higher meowfficer searching point per action points ratio.
        """
        logger.hr(f'OS meowfficer farming, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}', level=1)
        hazard1_mode = self.config.OpsiMeowfficerFarming_OperatingMode == 'hazard1_mode'
        if self.is_cl1_enabled and not hazard1_mode and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 1000:
            logger.info('With CL1 leveling enabled, set action point preserve to 1000')
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 1000

        if hazard1_mode:
            call_threshold = self.get_cl1_meowfficer_threshold()
            # Must read AP from screen since _action_point_total is 0 at task startup
            if not self.action_point_check(call_threshold):
                logger.info(f'Under hazard1_mode, current AP {self._action_point_total} is less than '
                            f'CL1 meowfficer threshold {call_threshold}. Delay to next period.')
                call_hazard1_back = False
                if self.config.is_task_enabled('OpsiHazard1Leveling'):
                    yellow_coins = self.get_yellow_coins()
                    yellow_coins_preserve = get_cl1_yellow_coins_preserve(self.config)
                    call_hazard1_back = yellow_coins > yellow_coins_preserve
                    if not call_hazard1_back:
                        logger.info(f'OpsiHazard1Leveling not called back because yellow coins {yellow_coins} '
                                    f'<= preserve {yellow_coins_preserve}')
                with self.config.multi_set():
                    self.config.task_delay(server_update=True)
                    if call_hazard1_back:
                        logger.info('AP is below CL1 meowfficer threshold, call OpsiHazard1Leveling back')
                        self.config.task_call('OpsiHazard1Leveling')
                self.config.task_stop()
            preserve = call_threshold
        else:
            preserve = min(self.get_action_point_limit(), self.config.OpsiMeowfficerFarming_ActionPointPreserve, 2000)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)
        if self.is_cl1_enabled:
            # Without these enabled, CL1 gains 0 profits
            self.config.override(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter='ActionPoint',
                OpsiFleet_Submarine=False,
            )
            cd = self.nearest_task_cooling_down
            logger.attr('Task cooling down', cd)
            # At the last day of every month, OpsiObscure and OpsiAbyssal are scheduled frequently
            # Don't schedule after them
            remain = get_os_reset_remain()
            if cd is not None and remain > 0:
                logger.info(f'Having task cooling down, delay OpsiMeowfficerFarming after it')
                self.config.task_delay(target=cd.next_run)
                self.config.task_stop()
        if self.is_in_opsi_explore():
            logger.warning(f'OpsiExplore is still running, cannot do {self.config.task.command}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        ap_checked = False
        while True:
            self.config.OS_ACTION_POINT_PRESERVE = preserve
            if self.config.is_task_enabled('OpsiAshBeacon') \
                    and not self._ash_fully_collected \
                    and self.config.cross_get("OpsiAshBeacon.OpsiAshBeacon.EnsureFullyCollected", True):
                logger.info('Ash beacon not fully collected, ignore action point limit temporarily')
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)
            if not ap_checked:
                # Check action points first to avoid using remaining AP when it not enough for tomorrow's daily
                # When not running CL1 and use oil
                keep_current_ap = True
                check_rest_ap = True
                if self.is_cl1_enabled and self.get_yellow_coins() >= get_cl1_yellow_coins_preserve(self.config):
                    check_rest_ap = False
                if not self.is_cl1_enabled and self.get_buy_action_point_limit() > 0:
                    keep_current_ap = False
                self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)
                ap_checked = True

            # (1252, 1012) is the coordinate of zone 134 (the center zone) in os_globe_map.png
            if self.config.OpsiMeowfficerFarming_TargetZone != 0:
                try:
                    zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
                except ScriptError:
                    logger.warning(f'wrong zone_id input:{self.config.OpsiMeowfficerFarming_TargetZone}')
                    raise RequestHumanTakeover('wrong input, task stopped')
                else:
                    logger.hr(f'OS meowfficer farming, zone_id={zone.zone_id}', level=1)
                    self.globe_goto(zone, refresh=True)
                    self.fleet_set(self.config.OpsiFleet_Fleet)
                    self.os_order_execute(
                        recon_scan=False,
                        submarine_call=self.config.OpsiFleet_Submarine)
                    self.run_auto_search()
                    self.handle_after_auto_search()
                    self.config.check_task_switch()
            else:
                zones = self.zone_select(hazard_level=self.config.OpsiMeowfficerFarming_HazardLevel) \
                    .delete(SelectedGrids([self.zone])) \
                    .delete(SelectedGrids(self.zones.select(is_port=True))) \
                    .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

                logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)
                self.globe_goto(zones[0])
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(
                    recon_scan=False,
                    submarine_call=self.config.OpsiFleet_Submarine)
                self.run_auto_search()
                self.handle_after_auto_search()
                self.config.check_task_switch()
