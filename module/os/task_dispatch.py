OPSI_MEOWFFICER_PRIORITY_TASKS = (
    ('OpsiStronghold', 'try_clear_stronghold'),
    ('OpsiAbyssal', 'try_clear_abyssal'),
    ('OpsiObscure', 'try_clear_obscure'),
)
OPSI_MEOWFFICER_FALLBACK_TASK = 'OpsiMeowfficerFarming'


def run_first_available(config, candidates, fallback):
    """Run only the highest-priority enabled candidate that reports availability."""
    for task, run in candidates:
        if not config.is_task_enabled(task):
            continue
        config.bind(task)
        if run():
            return task

    fallback_task, run_fallback = fallback
    config.bind(fallback_task)
    run_fallback()
    return fallback_task
