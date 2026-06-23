def get_cl1_yellow_coins_preserve(config):
    """
    Effective yellow coin preserve for CL1 handoff decisions.
    """
    preserve = config.cross_get(
        'OpsiHazard1Leveling.OpsiHazard1Leveling.YellowCoinsPreserve',
        config.OpsiHazard1Leveling_YellowCoinsPreserve)
    return max(0, int(preserve))
