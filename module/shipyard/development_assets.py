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


def is_task_action_label(label):
    """Return whether OCR still describes a known development action.

    The CN submit button is rendered with a bright outline and shadow.  On the
    live 2026-09-23 frame cnocr reads ``提交`` as only ``交`` even though the
    entire button is inside the OCR area.  Accept one missing glyph while
    keeping the observation an ordered subsequence of a known label.  The
    caller separately requires a known material row and exactly one enabled
    blue action, then verifies that the task becomes complete after the click.
    """
    if not isinstance(label, str):
        return False
    observed = label.replace(' ', '').replace('　', '').upper()
    if not observed:
        return False
    if observed == 'SUBMIT' or observed in TASK_ACTION_LABELS:
        return True

    for expected in TASK_ACTION_LABELS:
        if len(observed) < max(1, len(expected) - 1):
            continue
        iterator = iter(expected)
        if all(char in iterator for char in observed):
            return True
    return False


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
    rows by anchor keeps one row from being counted twice, which would
    otherwise make the inspector look for a title that no longer exists.

    The stage deliberately stays out of the hull-sculpting identity: the live
    panel reads ``利克斯·舒尔茨舰体塑造`` as often as ``…塑造II``, and keying on
    the stage made the inspector hunt for a title the panel never printed, then
    abort with "Material task is not visible".  Both stages are the same kind of
    material task, so one identity covers them and the remaining stage is
    submitted on the next pass.
    """
    normalised = normalise_cn_task_title(title)
    if HULL_SCULPT_ANCHOR in normalised:
        return (HULL_SCULPT_ANCHOR,)
    return normalised, 0


_CJK_ONLY = re.compile(r'[^\u4e00-\u9fff]')


def ship_name_similarity(left, right):
    """Longest common subsequence ratio of two readings of a ship name.

    The working-project label is short, and cnocr regularly drops or mangles a
    single character (``菲利克斯·舒尔茨`` read as ``利克昕舒尔茨``).  An exact
    comparison would abort a whole task over that noise, so the guard compares
    how much of the two readings still agrees.
    """
    a = _CJK_ONLY.sub('', left or '')
    b = _CJK_ONLY.sub('', right or '')
    if not a or not b:
        return 0.0
    previous = [0] * (len(b) + 1)
    for char_a in a:
        current = [0]
        for index, char_b in enumerate(b, 1):
            if char_a == char_b:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1] / max(len(a), len(b))


def task_title_area(header_y):
    return (TASK_TITLE_X[0], header_y + 21, TASK_TITLE_X[1], header_y + 48)


def task_header_button(header_y):
    return Button(
        area=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        color=(52, 72, 125),
        button=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        name=f'SHIPYARD_DEVELOPMENT_HEADER_{header_y}',
    )
