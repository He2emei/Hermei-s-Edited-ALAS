from module.config.utils import get_os_reset_remain
from module.logger import logger
from module.os.cl1 import can_run_cl1, get_cl1_yellow_coins_preserve, has_reached_cl1_meowfficer_threshold
from module.os.map import OSMap
from module.os.task_dispatch import (
    OPSI_HAZARD1_TASK,
    OPSI_MEOWFFICER_FALLBACK_TASK,
    OPSI_MEOWFFICER_PRIORITY_TASKS,
    run_first_available,
)
from module.os_handler.action_point import ActionPointLimit


class OpsiMeowfficerFarmingPriority(OSMap):
    PRIORITY_TASKS = OPSI_MEOWFFICER_PRIORITY_TASKS
    FALLBACK_TASK = OPSI_MEOWFFICER_FALLBACK_TASK
    HAZARD1_TASK = OPSI_HAZARD1_TASK

    def _delay_priority_dispatch_if_blocked(self):
        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is still running; delay unified CL1 priority dispatch')
            self.config.bind(self.FALLBACK_TASK)
            self.config.task_delay(server_update=True)
            return True
        if self.is_cl1_enabled:
            cooling_down = self.nearest_task_cooling_down
            logger.attr('Task cooling down', cooling_down)
            if cooling_down is not None and get_os_reset_remain() > 0:
                self.config.bind(self.FALLBACK_TASK)
                self.config.task_delay(target=cooling_down.next_run)
                return True
        return False

    def _can_resume_hazard1(self):
        if not self.config.is_task_enabled(self.HAZARD1_TASK):
            return False
        return can_run_cl1(self.get_yellow_coins(), get_cl1_yellow_coins_preserve(self.config))

    def _resume_hazard1(self):
        self.config.bind(self.FALLBACK_TASK)
        self.config.task_delay(success=True)
        self.config.task_call(self.HAZARD1_TASK)

    def _try_high_value_task(self, task, method):
        try:
            return getattr(self, method)()
        except ActionPointLimit:
            logger.info(f'{task} does not have enough action points; try the next priority')
            return False

    def os_meowfficer_farming_priority(self):
        """
        Coordinate CL1, high-value OpSi maps, and meowfficer farming.

        Above the AP threshold, clear high-value maps before shortcat. Below
        the threshold, resume CL1 while it has yellow-coin fuel; otherwise use
        high-value maps to recover fuel without ever falling back to shortcat.
        """
        if self._delay_priority_dispatch_if_blocked():
            return None

        threshold = self.get_cl1_meowfficer_threshold()
        self.action_point_check(threshold)
        action_points_reached = has_reached_cl1_meowfficer_threshold(self._action_point_total, threshold)
        if not action_points_reached:
            if self._can_resume_hazard1():
                logger.info(f'Action points are below {threshold}, resume OpsiHazard1Leveling')
                self._resume_hazard1()
                return self.HAZARD1_TASK
            fallback = None
        else:
            fallback = (self.FALLBACK_TASK, self.os_meowfficer_farming)

        selected = run_first_available(
            self.config,
            [
                (task, lambda task=task, method=method: self._try_high_value_task(task, method))
                for task, method in self.PRIORITY_TASKS
            ],
            fallback,
        )
        logger.attr('Meowfficer priority task', selected)
        if selected is None:
            logger.info('No high-value OpSi task is currently available; shortcat remains blocked')
            self.config.bind(self.FALLBACK_TASK)
            self.config.task_delay(success=False)
            return None
        if selected != self.FALLBACK_TASK:
            # The meowfficer scheduler supplied the trigger, so consume it even
            # when a higher-priority task was selected.
            self.config.bind(self.FALLBACK_TASK)
            self.config.task_delay(success=True)
            if not action_points_reached and self._can_resume_hazard1():
                logger.info('High-value OpSi task restored CL1 fuel; resume OpsiHazard1Leveling')
                self.config.task_call(self.HAZARD1_TASK)
            else:
                self.config.task_call(self.FALLBACK_TASK)
        return selected
