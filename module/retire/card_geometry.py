"""Screenshot-derived card geometry for scrolling CN docks."""
import cv2

from module.base.button import Button
from module.exception import RequestHumanTakeover


def dock_cards(image):
    """Locate level labels after scrolling; the dock does not snap to a grid."""
    template = cv2.imread('./assets/cn/opsi_training/dock_lv.png', 0)
    if template is None:
        raise RequestHumanTakeover('Dock level label asset missing')
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    detected = []
    for col in range(7):
        x = round(93 + col * (164 + 2 / 3))
        scores = cv2.matchTemplate(gray[75:625, x + 60:x + 138], template, cv2.TM_CCOEFF_NORMED)
        while scores.max() > 0.78:
            _, _, _, (_, y) = cv2.minMaxLoc(scores)
            top = y + 75 - 10
            scores[max(0, y - 35):y + 36] = 0
            if top >= 70 and top + 204 <= 625:
                detected.append((top, col))
    # A row's cards share the same origin. Individual level labels may be
    # obscured by portrait colors, so corroborate the row across columns.
    rows = []
    for top, col in sorted(detected):
        if not rows or top - rows[-1][-1][0] > 4:
            rows.append([])
        rows[-1].append((top, col))
    cards = []
    for row in rows:
        if len({col for _, col in row}) < 2:
            continue
        top = sorted(y for y, _ in row)[len(row) // 2]
        for col in range(7):
            x = round(93 + col * (164 + 2 / 3))
            area = (x, top, x + 138, top + 204)
            cards.append(Button(area, (0, 0, 0), (x + 15, top + 45, x + 120, top + 150), name=f'TRAINING_CARD_{col}_{top}'))
    return cards
