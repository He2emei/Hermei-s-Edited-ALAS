from time import time

from module.base.timer import Timer
from module.combat.assets import BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D, BATTLE_STATUS_S
from module.logger import logger

# Buttons of the battle result screen, ordered like Combat.handle_battle_status().
# Their area is the rank icon, which is the recognition signal, and their button is the
# clickable area of the result screen, which is the localization of the skip target.
BATTLE_RESULT_BUTTONS = (BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D)

# Interval between two "skip the result screen" clicks, same as Combat.battle_status_click_interval.
battle_result_click_timer = Timer(2, count=0)
# Clicks spent on the result screen that is on the display right now.
battle_result_attempt = 0
# Time of the last click, to tell a still blocked screen from a new battle.
battle_result_clicked_at = 0.

# A result screen that no combat loop skipped is clicked at most this many times, then the page
# poll reports the page again instead of clicking forever.
BATTLE_RESULT_MAX_ATTEMPT = 3
# A result screen that is still there this long after the last click belongs to a new battle.
BATTLE_RESULT_STALE = 10


def match_battle_result_button(image):
    """
    Detect the battle result screen.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        Button: The matched result-screen button, or None.
    """
    for button in BATTLE_RESULT_BUTTONS:
        if button.appear_on(image):
            return button

    return None


def handle_battle_result_screen(app):
    """
    Skip a battle result screen that is left on the display.

    Alas polls the pages it knows in UI.ui_get_current_page(), but a result screen of an
    ongoing combat is not a page and it is not in the page list. A result screen blocking the
    display therefore ends in GamePageUnknownError as soon as the scheduler polls the current
    page, for example when the scheduler is restarted while a battle is running (live
    2026-09-20 15:48:25 and 15:51:12, GemsFarming on event a3, both CRITICAL `Game page unknown`).

    The combat loops skip a result screen through Combat.handle_battle_status(), but that handler
    is not reachable from the page detection of UI, and
    AutoSearchCombat.auto_search_combat_status() only reaches it when a low-emotion popup armed
    `_auto_search_status_confirm`. A result screen left over from a battle that no combat loop
    finished therefore has no handler at all, in the page poll as well as in the operation siren
    map loops, which wait for is_in_map() and never click a result screen (live 2026-09-20 23:08:25,
    OpsiHazard1Leveling in os_auto_search_quit, GameStuckError).

    The rank icon recognizes the screen and the button area of the same asset is the skip target,
    so no new template or screen layout is assumed here. The click target is the Button itself,
    because Device.click() takes a Button and reads its `button` attribute; a coordinate of that
    area is not a click target and crashed the task with `AttributeError: 'tuple' object has no
    attribute 'button'` (live 2026-09-21 05:52:59, dump log/error/1789941179502). The click is
    repeated BATTLE_RESULT_MAX_ATTEMPT times because a single click can be swallowed by the game,
    and then the screen is left to the page poll.

    Args:
        app: Alas instance.

    Returns:
        bool: If clicked.
    """
    global battle_result_attempt, battle_result_clicked_at

    if not battle_result_click_timer.reached():
        return False

    button = match_battle_result_button(app.device.image)
    if button is None:
        battle_result_attempt = 0
        return False

    # A battle in progress is an unsupported start state as well, but never click into it.
    # This probe is asked only once the screen is on the display, because Combat.is_combat_executing()
    # registers PAUSE in the stuck record of the device, and a loop that never sees a result screen
    # would otherwise lose its sixty second stuck check.
    in_combat = getattr(app, 'is_combat_executing', None)
    if callable(in_combat) and in_combat():
        return False

    # A screen that is still there long after the last click belongs to a new battle.
    if time() - battle_result_clicked_at > BATTLE_RESULT_STALE:
        battle_result_attempt = 0

    if battle_result_attempt >= BATTLE_RESULT_MAX_ATTEMPT:
        logger.warning(f'Unable to skip the battle result screen: {button}')
        return False

    battle_result_attempt += 1
    battle_result_clicked_at = time()
    logger.info(f'Skip battle result: {button}, attempt {battle_result_attempt}')
    # Device.click() takes a Button, not a coordinate: it reads `button.button`, which is the
    # clickable area of the result screen, and registers the button in the click record.
    app.device.click(button)
    battle_result_click_timer.reset()
    return True
