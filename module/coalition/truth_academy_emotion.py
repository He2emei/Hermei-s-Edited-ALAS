"""Read-only matcher for the one verified CN Truth Academy low-mood toast."""
from pathlib import Path

import cv2
import numpy as np


TOAST_ROI = (343, 308, 934, 339)  # x1, y1, x2, y2
TOAST_THRESHOLD = 130
TOAST_MIN_SCORE = 0.995
TOAST_TEMPLATE = Path('./assets/cn/coalition/TRUTH_LOW_MOOD_TOAST.png')


class TruthAcademyEmotionReader:
    """Match only the generic warning text crop; caller owns page/event gates."""

    def __init__(self, template_path=None):
        path = str(template_path or TOAST_TEMPLATE)
        self.template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        expected = (TOAST_ROI[3] - TOAST_ROI[1], TOAST_ROI[2] - TOAST_ROI[0])
        if self.template is None or self.template.shape != expected:
            raise ValueError('Truth Academy low-mood template is missing or has wrong dimensions')

    @staticmethod
    def _binary_rgb(image):
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, TOAST_THRESHOLD, 255, cv2.THRESH_BINARY)
        return binary

    def read_low_mood_toast(self, image):
        """Return True for the exact fixed-ROI toast, False for unknown frames."""
        if image is None or getattr(image, 'shape', None) != (720, 1280, 3):
            return False
        x1, y1, x2, y2 = TOAST_ROI
        roi = image[y1:y2, x1:x2]
        if roi.shape != self.template.shape + (3,):
            return False
        binary = self._binary_rgb(roi)
        score = cv2.matchTemplate(binary, self.template, cv2.TM_CCOEFF_NORMED)[0, 0]
        return bool(score >= TOAST_MIN_SCORE)
