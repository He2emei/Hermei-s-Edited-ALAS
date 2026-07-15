from datetime import date, datetime, timedelta

from module.config.opsi_constants import OPSI_BUY_ACTION_POINT_MANUAL_AT

MANUAL_AT = OPSI_BUY_ACTION_POINT_MANUAL_AT
MIGRATION_WEEK_START = date(2026, 7, 13)


def _week_start(day):
    return day - timedelta(days=day.weekday())


class ActionPointLimitPolicy:
    def _log_action_point_limit(self, buy_limit, source):
        pass

    def get_buy_action_point_limit(self, today=None):
        if today is None:
            today = datetime.now().date()

        manual_at = self.config.cross_get(MANUAL_AT, default=None)
        if manual_at is None and _week_start(today) == MIGRATION_WEEK_START:
            manual_at = datetime.combine(today, datetime.min.time())
            self.config.cross_set(MANUAL_AT, manual_at.strftime('%Y-%m-%d %H:%M:%S'))
            buy_limit = self.config.OpsiGeneral_BuyActionPointLimit
            self._log_action_point_limit(buy_limit, source='migration')
            return buy_limit
        if isinstance(manual_at, str):
            manual_at = datetime.fromisoformat(manual_at)
        if isinstance(manual_at, datetime) and _week_start(manual_at.date()) == _week_start(today):
            buy_limit = self.config.OpsiGeneral_BuyActionPointLimit
            self._log_action_point_limit(buy_limit, source='manual')
            return buy_limit

        month_start = today.replace(day=1)
        first_week_end = 1 + (6 - month_start.weekday())
        second_week_end = first_week_end + 7
        buy_limit = 5 if today.day <= second_week_end else 0
        if self.config.OpsiGeneral_BuyActionPointLimit != buy_limit:
            self.config.OpsiGeneral_BuyActionPointLimit = buy_limit
        self._log_action_point_limit(buy_limit, source='automatic')
        return buy_limit
