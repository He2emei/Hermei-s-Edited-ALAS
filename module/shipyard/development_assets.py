"""Geometry and conservative visual guards for CN shipyard development."""

import re

from module.base.button import Button


SUPPORTED_SIZE = (1280, 720)

# These regions are taken from the supplied 1280x720 CN evidence.  The
# development implementation intentionally uses OCR inside them instead of
# adding broad templates that could match blueprint strengthening screens.
SHIP_NAME_AREA = (610, 91, 790, 126)
TASK_LIST_AREA = (945, 130, 1275, 558)
TASK_HEADER_X = (945, 1275)
TASK_TITLE_X = (990, 1270)
TASK_SCAN_ROWS = 8

# The action is derived from the currently expanded row, never from the
# ordinary shipyard confirm/buy buttons.
TASK_ACTION_LABELS = frozenset({'提交', '完成', '立即完成'})

# Every locked task prints its countdown on the title line, right-aligned to
# the panel edge, and a long title runs straight into it without a separator
# (verified on the CN panel, 2026-09-16).  The countdown therefore arrives as
# part of the OCR result and must be removed before anything is compared.
_TRAILING_TIMER = re.compile(r'[\d:：]+$')

# cnocr renders the stage strokes inconsistently: a stage I is often read as a
# lower-case L, a pipe, or a digit one; a stage II as two Ls or the double
# stroke character.  Normalise all of them to the ASCII form used by the
# catalog.
_OCR_LETTERS = str.maketrans({
    'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III',
    '‖': 'II', '∣': 'I', '｜': 'I', '丨': 'I',
    'l': 'I', 'L': 'I', '|': 'I',
})

# Hull sculpting repeats the same task text for every ship, and the development
# panel only ever lists the project that is being developed, so an unrecognised
# ship name still describes a known material task.
HULL_SCULPT_ANCHOR = '舰体塑'

# Stage II is the only stage with a two-stroke suffix, so anything shorter is
# treated as stage I.  A suffix eaten by the countdown then keeps the same
# identity instead of producing a second, duplicate row.
STAGE_TWO = 2
STAGE_ONE = 1


def strip_cn_task_timer(text):
    """Remove a trailing countdown such as ``23:54:44`` from a task title."""
    if not isinstance(text, str):
        return ''
    match = _TRAILING_TIMER.search(text)
    if not match:
        return text
    token = match.group()
    # A lone trailing digit is not a countdown: it is how cnocr renders the
    # stage stroke sitting next to the timer, and dropping it would lose the
    # stage.  Only a token with a clock separator is a timer.
    if ':' not in token and '：' not in token:
        return text
    return text[:match.start()]


def normalise_cn_task_title(title):
    """Normalise an OCRed CN task title so it can be compared reliably."""
    if not isinstance(title, str):
        return ''
    title = title.replace(' ', '').replace('　', '')
    title = title.translate(_OCR_LETTERS)
    return strip_cn_task_timer(title)


def task_stage(title):
    """Return the stage encoded in a task title, defaulting to stage I."""
    normalised = normalise_cn_task_title(title)
    return STAGE_TWO if normalised.endswith('II') else STAGE_ONE


def task_identity(title):
    """Return a comparison key that survives ship-name noise and OCR drift.

    Two observations of the same row may differ in a dropped leading character
    or in a stage stroke swallowed by the countdown.  Grouping hull-sculpting
    rows by anchor and stage keeps one row from being counted twice, which
    would otherwise make the inspector look for a title that no longer exists.
    """
    normalised = normalise_cn_task_title(title)
    if HULL_SCULPT_ANCHOR in normalised:
        return HULL_SCULPT_ANCHOR, STAGE_TWO if normalised.endswith('II') else STAGE_ONE
    return normalised, 0


def task_title_area(header_y):
    return (TASK_TITLE_X[0], header_y + 21, TASK_TITLE_X[1], header_y + 48)


def task_header_button(header_y):
    return Button(
        area=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        color=(52, 72, 125),
        button=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        name=f'SHIPYARD_DEVELOPMENT_HEADER_{header_y}',
    )
