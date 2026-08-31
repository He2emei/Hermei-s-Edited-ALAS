from module.config.utils import get_os_reset_remain
from module.os_shop.monthly import (
    CROSS_MONTH_ACTION_POINT_YELLOW_COINS,
    should_reserve_cross_month_action_points,
)


def get_cl1_yellow_coins_preserve(config, reset_remain=None):
    """
    Effective yellow coin preserve for CL1 admission decisions.

    This is intentionally not a hard cap inside an admitted CL1 run: when an
    Akashi shop offers AP, the existing rule still buys it even if the purchase
    takes the balance below this line.
    """
    preserve = config.cross_get(
        'OpsiHazard1Leveling.OpsiHazard1Leveling.YellowCoinsPreserve',
        config.OpsiHazard1Leveling_YellowCoinsPreserve)
    preserve = max(0, int(preserve))
    if reset_remain is None:
        reset_remain = get_os_reset_remain()
    if should_reserve_cross_month_action_points(config, reset_remain):
        preserve = max(preserve, CROSS_MONTH_ACTION_POINT_YELLOW_COINS)
    return preserve


def has_reached_cl1_meowfficer_threshold(action_points, threshold):
    """Whether AP has reached the shared CL1-to-shortcat handoff threshold."""
    return int(action_points) >= int(threshold)


def can_run_cl1(yellow_coins, fuel_line):
    """Whether yellow coins are above the minimum fuel line for another CL1 run."""
    return int(yellow_coins) > int(fuel_line)
