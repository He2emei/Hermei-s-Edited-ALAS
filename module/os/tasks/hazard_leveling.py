from module.logger import logger
from module.os.cl1 import get_cl1_yellow_coins_preserve
from module.os.map import OSMap


class OpsiHazard1Leveling(OSMap):
    def os_hazard1_leveling(self):
        logger.hr('OS hazard 1 leveling', level=1)
        # Without these enabled, CL1 gains 0 profits
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_AkashiShopFilter='ActionPoint',
        )
        if not self.config.is_task_enabled('OpsiMeowfficerFarming'):
            self.config.cross_set(keys='OpsiMeowfficerFarming.Scheduler.Enable', value=True)
        while True:
            # Limited action point preserve of hazard 1, configurable via GUI
            self.config.OS_ACTION_POINT_PRESERVE = self.config.OpsiHazard1Leveling_ActionPointPreserve
            if self.config.is_task_enabled('OpsiAshBeacon') \
                    and not self._ash_fully_collected \
                    and self.config.cross_get("OpsiAshBeacon.OpsiAshBeacon.EnsureFullyCollected", True):
                logger.info('Ash beacon not fully collected, ignore action point limit temporarily')
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)

            yellow_coins_preserve = get_cl1_yellow_coins_preserve(self.config)
            if self.get_yellow_coins() < yellow_coins_preserve:
                logger.info(f'Reach the limit of yellow coins, preserve={yellow_coins_preserve}')
                with self.config.multi_set():
                    self.config.task_delay(server_update=True)
                    if not self.is_in_opsi_explore():
                        cd = self.nearest_task_cooling_down
                        if cd is None:
                            for task in ['OpsiAbyssal', 'OpsiStronghold', 'OpsiObscure']:
                                if self.config.is_task_enabled(task):
                                    self.config.task_call(task)
                        self.config.task_call('OpsiMeowfficerFarming')
                self.config.task_stop()

            self.get_current_zone()

            # Preset action point to 70
            # When running CL1 oil is for running CL1, not meowfficer farming
            keep_current_ap = True
            self.action_point_set(cost=5, keep_current_ap=keep_current_ap, check_rest_ap=True)
            call_threshold = self.get_cl1_meowfficer_threshold()
            if self._action_point_total > call_threshold:
                with self.config.multi_set():
                    self.config.task_delay(server_update=True)
                    if not self.is_in_opsi_explore():
                        cd = self.nearest_task_cooling_down
                        if cd is None:
                            for task in ['OpsiAbyssal', 'OpsiStronghold', 'OpsiObscure']:
                                if self.config.is_task_enabled(task):
                                    self.config.task_call(task)
                        self.config.task_call('OpsiMeowfficerFarming')
                self.config.task_stop()

            if self.config.OpsiHazard1Leveling_TargetZone != 0:
                zone = self.config.OpsiHazard1Leveling_TargetZone
            else:
                zone = 22
            logger.hr(f'OS hazard 1 leveling, zone_id={zone}', level=1)
            if self.zone.zone_id != zone or not self.is_zone_name_hidden:
                self.globe_goto(self.name_to_zone(zone), types='SAFE', refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.run_strategic_search()

            self.handle_after_auto_search()
            self.config.check_task_switch()
