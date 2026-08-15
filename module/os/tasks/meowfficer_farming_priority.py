from module.config.utils import get_os_reset_remain
from module.logger import logger
from module.os.map import OSMap
from module.os.task_dispatch import (
    OPSI_MEOWFFICER_FALLBACK_TASK,
    OPSI_MEOWFFICER_PRIORITY_TASKS,
    run_first_available,
)


class OpsiMeowfficerFarmingPriority(OSMap):
    PRIORITY_TASKS = OPSI_MEOWFFICER_PRIORITY_TASKS
    FALLBACK_TASK = OPSI_MEOWFFICER_FALLBACK_TASK

    def _priority_dispatch_blocked(self):
        if self.is_in_opsi_explore():
            return True
        if self.is_cl1_enabled:
            cooling_down = self.nearest_task_cooling_down
            logger.attr('Task cooling down', cooling_down)
            if cooling_down is not None and get_os_reset_remain() > 0:
                return True
        return False

    def os_meowfficer_farming_priority(self):
        """Run the first available limited OpSi task, falling back to meowfficer farming."""
        if self._priority_dispatch_blocked():
            self.config.bind(self.FALLBACK_TASK)
            self.os_meowfficer_farming()
            return self.FALLBACK_TASK

        selected = run_first_available(
            self.config,
            [
                (task, getattr(self, method))
                for task, method in self.PRIORITY_TASKS
            ],
            (self.FALLBACK_TASK, self.os_meowfficer_farming),
        )
        logger.attr('Meowfficer priority task', selected)
        if selected != self.FALLBACK_TASK:
            # The meowfficer scheduler supplied the trigger, so consume it even
            # when a higher-priority task was selected.
            self.config.bind(self.FALLBACK_TASK)
            self.config.task_delay(success=True)
        return selected
