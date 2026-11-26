"""Read-only recognition of the CN Truth Academy event pages.

This module deliberately does not navigate, prepare a fleet, or start a battle.
"""

from module.base.button import Button
from module.base.utils import get_color
from module.ocr.ocr import Digit


def _button(name, area, color=(255, 255, 255), click_area=None):
    return Button(
        area={'cn': area},
        color={'cn': color},
        button={'cn': click_area or area},
        file=f'./assets/cn/coalition/{name}.png',
    )


# Main event page anchors
TRUTH_MAIN_CHECK = _button('TRUTH_MAIN_CHECK', (118, 34, 392, 111))
TRUTH_HOME = _button('TRUTH_HOME', (1192, 27, 1257, 104))
TRUTH_EASY = _button('TRUTH_EASY', (155, 276, 213, 311))
TRUTH_BATTLE_STORY_SELECTOR = _button('TRUTH_BATTLE_STORY_SELECTOR', (163, 618, 212, 680))
TRUTH_PT_ENTRY = _button('TRUTH_PT_ENTRY', (1110, 181, 1279, 253))

# Stable simple student-dorm preparation page anchor. The recommendation action
# changes other preparation fields, so do not use those values as page identity.
TRUTH_PREP_CHECK = _button('TRUTH_PREP_CHECK', (930, 120, 1070, 157))
TRUTH_CLOSE = _button('TRUTH_CLOSE', (1185, 48, 1248, 104))
TRUTH_PROCEED = _button('TRUTH_PROCEED', (928, 513, 1228, 582))
TRUTH_RECOMMEND = _button('TRUTH_RECOMMEND', (759, 223, 833, 291))
TRUTH_NORMAL_PREP_CHECK = _button('TRUTH_NORMAL_PREP_CHECK', (934, 121, 1064, 157))
TRUTH_HARD_PREP_CHECK = _button('TRUTH_HARD_PREP_CHECK', (934, 121, 1064, 157))
TRUTH_EMPTY_SLOT = _button('TRUTH_EMPTY_SLOT', (247, 238, 274, 267))

TRUTH_LEVEL_ROIS = [
    (269, 219, 292, 239), (357, 219, 380, 239), (445, 219, 468, 239),
    (533, 219, 556, 239), (621, 219, 644, 239), (708, 219, 731, 239),
]

# Generic reward-page anchors and safe exits. Button templates are synthetic
# black canvases containing only the cropped, non-account-specific UI region.
TRUTH_BATTLE_RESULT_TITLE = _button('TRUTH_BATTLE_RESULT_TITLE', (50, 75, 309, 123))
TRUTH_BATTLE_RESULT_CONFIRM = _button(
    'TRUTH_BATTLE_RESULT_CONFIRM', (1108, 646, 1182, 676),
    color=(232, 186, 123), click_area=(1088, 640, 1203, 682))
TRUTH_TOTAL_REWARDS_TITLE = _button('TRUTH_TOTAL_REWARDS_TITLE', (371, 78, 585, 114))
TRUTH_TOTAL_REWARDS_LEAVE = _button(
    'TRUTH_TOTAL_REWARDS_LEAVE', (411, 607, 476, 637),
    color=(184, 187, 189), click_area=(403, 603, 485, 641))


class TruthAcademyReader:
    """Classify verified event pages; reject every unmatched page."""

    @staticmethod
    def _matches(image, button, similarity=0.90):
        return button.match(image, offset=0, similarity=similarity)

    def read(self, image):
        """Return ``main``, ``simple_preparation``, or ``unknown``.

        The input must be a CN 1280x720 RGB image in the format used by ALAS.
        Page recognition requires all anchors for a page to match.
        """
        if image is None or image.shape != (720, 1280, 3):
            return 'unknown'

        main_anchors = (
            TRUTH_MAIN_CHECK,
            TRUTH_HOME,
            TRUTH_EASY,
            TRUTH_BATTLE_STORY_SELECTOR,
            TRUTH_PT_ENTRY,
        )
        if all(self._matches(image, button) for button in main_anchors):
            return 'main'

        prep_anchors = (
            TRUTH_PREP_CHECK,
            TRUTH_CLOSE,
            TRUTH_PROCEED,
            TRUTH_RECOMMEND,
        )
        if all(self._matches(image, button) for button in prep_anchors):
            return 'simple_preparation'

        normal_prep_anchors = (TRUTH_NORMAL_PREP_CHECK, TRUTH_CLOSE, TRUTH_PROCEED)
        if all(self._matches(image, button) for button in normal_prep_anchors):
            return 'normal_preparation'

        hard_prep_anchors = (TRUTH_HARD_PREP_CHECK, TRUTH_CLOSE, TRUTH_PROCEED)
        if all(self._matches(image, button) for button in hard_prep_anchors):
            return 'hard_preparation'

        return 'unknown'

    def read_fleet_mode(self, image):
        """Return single/multi only on a positively recognized preparation page."""
        page = self.read(image)
        if page == 'simple_preparation':
            return 'single'
        if page not in ('normal_preparation', 'hard_preparation'):
            return 'unknown'
        left = get_color(image, (949, 390, 959, 400))
        right = get_color(image, (1089, 390, 1099, 400))
        left_blue = left[2] - left[0] > 20 and left[1] - left[0] > 5
        right_blue = right[2] - right[0] > 20 and right[1] - right[0] > 5
        if left_blue == right_blue:
            return 'unknown'
        return 'single' if left_blue else 'multi'

    def read_fleet_levels(self, image):
        """Return six verified levels/empty slots, or None for ambiguous OCR."""
        if self.read(image) not in ('simple_preparation', 'normal_preparation', 'hard_preparation'):
            return None
        levels = Digit(TRUTH_LEVEL_ROIS, name='TRUTH_FLEET_LEVELS', lang='azur_lane',
                       letter=(214, 232, 255), threshold=128).ocr(image)
        if levels is None or len(levels) != 6:
            return None
        result = []
        for index, level in enumerate(levels):
            if level is None:
                return None
            try:
                level = int(level)
            except (TypeError, ValueError):
                return None
            if 1 <= level <= 125:
                result.append(level)
            elif level == 0:
                dx = 88 * index
                if not TRUTH_EMPTY_SLOT.match(image, offset=(dx - 8, -5, dx + 8, 5), similarity=0.90):
                    return None
                result.append(0)
            else:
                return None
        if not any(result[:3]) or not any(result[3:]):
            return None
        return tuple(result)

    def read_reward(self, image):
        """Return a settlement type only when title and safe button both match."""
        if image is None or image.shape != (720, 1280, 3):
            return 'unknown'

        battle_result = (
            self._matches(image, TRUTH_BATTLE_RESULT_TITLE) and
            self._matches(image, TRUTH_BATTLE_RESULT_CONFIRM)
        )
        total_rewards = (
            self._matches(image, TRUTH_TOTAL_REWARDS_TITLE) and
            self._matches(image, TRUTH_TOTAL_REWARDS_LEAVE)
        )
        if battle_result == total_rewards:
            return 'unknown'
        if battle_result:
            return 'battle_result'
        return 'total_rewards'
