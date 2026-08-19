def get_cl1_yellow_coins_preserve(config):
    """
    Effective yellow coin preserve for CL1 handoff decisions.
    """
    preserve = config.cross_get(
        'OpsiHazard1Leveling.OpsiHazard1Leveling.YellowCoinsPreserve',
        config.OpsiHazard1Leveling_YellowCoinsPreserve)
    return max(0, int(preserve))


def has_reached_cl1_meowfficer_threshold(action_points, threshold):
    """Whether AP has reached the shared CL1-to-shortcat handoff threshold."""
    return int(action_points) >= int(threshold)


def can_run_cl1(yellow_coins, fuel_line):
    """Whether yellow coins are above the minimum fuel line for another CL1 run."""
    return int(yellow_coins) > int(fuel_line)
