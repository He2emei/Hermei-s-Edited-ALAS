from module.exception import RequestHumanTakeover


BLUEPRINT_KEYS = ('destroyer', 'cruiser', 'battleship', 'carrier')


def select_hard_stage(stage, counts):
    """Select the least-stocked gold blueprint drop within a hard chapter."""
    try:
        chapter_text, map_text = str(stage).split('-', 1)
        chapter = int(chapter_text)
        configured_map = int(map_text)
    except (TypeError, ValueError):
        raise RequestHumanTakeover('Invalid Hard_HardStage')

    if chapter < 3 or configured_map not in range(1, 5):
        raise RequestHumanTakeover('Hard stage does not produce gold retrofit blueprints')
    if not isinstance(counts, dict) or set(counts) != set(BLUEPRINT_KEYS):
        raise RequestHumanTakeover('Incomplete hard blueprint inventory')
    if any(isinstance(counts[key], bool) or not isinstance(counts[key], int)
           or counts[key] < 0 for key in BLUEPRINT_KEYS):
        raise RequestHumanTakeover('Invalid hard blueprint inventory')

    # Keep the configured map first among ties, then use the smallest map number.
    order = sorted(
        range(1, 5),
        key=lambda map_number: (
            counts[BLUEPRINT_KEYS[map_number - 1]],
            0 if map_number == configured_map else 1,
            map_number,
        ),
    )
    return f'{chapter}-{order[0]}'
