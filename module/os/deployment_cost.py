"""Read the CN OpSi fleet-deployment confirmation before spending AP."""

import re

import cv2
import numpy as np

from module.ocr.ocr import Ocr


def read_deployment_cost(image):
    """Return the displayed AP cost, or None unless the whole guard is clear."""
    message = Ocr([(370, 290, 900, 335)], lang='cnocr',
                  name='TrainingDeploymentMessage').ocr(image).replace(' ', '')
    if not all(part in message for part in ('舰队部署', '消耗', '行动力', '是否继续')):
        return None

    # The cost is green whereas the surrounding sentence is white.  Ordinary
    # line OCR drops this isolated coloured digit (verified on a live CN frame).
    region = image[289:330, 610:755]
    r, g, b = cv2.split(region)
    mask = np.uint8((g > r.astype('int16') + 45)
                    & (g > b.astype('int16') + 45)
                    & (g > 120) & (r < 170)) * 255
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    glyphs = [(x, y, w, h) for x, y, w, h, area in stats[1:count]
              if area >= 12 and h >= 12 and 4 <= w <= 22]
    if not 1 <= len(glyphs) <= 3:
        return None
    left = min(x for x, _, _, _ in glyphs)
    top = min(y for _, y, _, _ in glyphs)
    right = max(x + w for x, _, w, _ in glyphs)
    bottom = max(y + h for _, y, _, h in glyphs)
    if not (16 <= bottom - top <= 25 and right - left <= 55):
        return None
    digit = mask[max(0, top - 2):min(mask.shape[0], bottom + 2),
                 max(0, left - 2):min(mask.shape[1], right + 2)]
    digit = cv2.copyMakeBorder(digit, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=0)
    digit = cv2.cvtColor(digit, cv2.COLOR_GRAY2RGB)
    result = Ocr([(0, 0, digit.shape[1], digit.shape[0])], lang='cnocr',
                 alphabet='0123456789', name='TrainingDeploymentCost').ocr(digit)
    if result == '0' and len(glyphs) != 1:
        return None
    return int(result) if re.fullmatch(r'\d{1,3}', result) else None
