LARGE_ACTION_POINT_ITEM = 'actionpoint100'
LARGE_ACTION_POINT_BOX_COUNT = 4
LARGE_ACTION_POINT_BOX_PRICE = 5_000
CROSS_MONTH_RESERVE_START_DAYS = 2
CROSS_MONTH_ACTION_POINT_YELLOW_COINS = \
    LARGE_ACTION_POINT_BOX_COUNT * LARGE_ACTION_POINT_BOX_PRICE


def is_large_action_point_item(item):
    """Whether an item is one of the 100-AP monthly port-shop boxes."""
    return item.name.lower() == LARGE_ACTION_POINT_ITEM


def should_reserve_cross_month_action_points(config, reset_remain):
    """Whether yellow coins and large AP boxes should be held for reset."""
    return (
        config.is_task_enabled('OpsiCrossMonth')
        and reset_remain <= CROSS_MONTH_RESERVE_START_DAYS
    )
