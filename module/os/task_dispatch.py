OPSI_MEOWFFICER_PRIORITY_TASKS = (
    ('OpsiStronghold', 'try_clear_stronghold'),
    ('OpsiAbyssal', 'try_clear_abyssal'),
    ('OpsiObscure', 'try_clear_obscure'),
)
OPSI_MEOWFFICER_FALLBACK_TASK = 'OpsiMeowfficerFarming'
OPSI_HAZARD1_TASK = 'OpsiHazard1Leveling'


def run_first_available(config, candidates, fallback):
    """Run the highest-priority candidate that reports availability."""
    for task, run in candidates:
        config.bind(task)
        if run():
            return task

    if fallback is None:
        return None

    fallback_task, run_fallback = fallback
    config.bind(fallback_task)
    run_fallback()
    return fallback_task
