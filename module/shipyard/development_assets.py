"""Geometry and conservative visual guards for CN shipyard development."""

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


def normalise_cn_task_title(title):
    if not isinstance(title, str):
        return ''
    return title.replace(' ', '').replace('　', '').replace('Ⅰ', 'I').replace('Ⅱ', 'II').replace('l', 'I')


def task_title_area(header_y):
    return (TASK_TITLE_X[0], header_y + 21, TASK_TITLE_X[1], header_y + 48)


def task_header_button(header_y):
    return Button(
        area=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        color=(52, 72, 125),
        button=(TASK_HEADER_X[0], header_y, TASK_HEADER_X[1], header_y + 52),
        name=f'SHIPYARD_DEVELOPMENT_HEADER_{header_y}',
    )
