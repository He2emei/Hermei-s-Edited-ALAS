from time import monotonic, time

from module.base.timer import Timer
from module.combat.assets import (BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D,
                                  BATTLE_STATUS_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D,
                                  EXP_INFO_S, QUIT_RECONFIRM)
from module.combat_ui.assets import (PAUSE, PAUSE_AzureCore, PAUSE_Christmas, PAUSE_Cyber, PAUSE_Devil,
                                     PAUSE_ElvenVine, PAUSE_GildedReverie, PAUSE_HolyLight,
                                     PAUSE_Iridescent_Fantasy, PAUSE_MaidCafe, PAUSE_Neon, PAUSE_New,
                                     PAUSE_Ninja, PAUSE_Nurse, PAUSE_OldeRoyal, PAUSE_Pharaoh, PAUSE_Ritual,
                                     PAUSE_Seaside, PAUSE_ShadowPuppetry, PAUSE_SpringInn, PAUSE_Star,
                                     PAUSE_Ancient, PAUSE_YoRHa, QUIT, QUIT_Christmas, QUIT_Cyber,
                                     QUIT_GildedReverie, QUIT_Iridescent_Fantasy, QUIT_MaidCafe, QUIT_New,
                                     QUIT_Ninja, QUIT_Nurse, QUIT_Pharaoh, QUIT_Ritual, QUIT_Seaside,
                                     QUIT_SpringInn, QUIT_YoRHa)
from module.logger import logger
from module.ui.assets import MAIN_GOTO_FLEET
from module.ui_white.assets import MAIN_GOTO_CAMPAIGN_WHITE

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


# ---------------------------------------------------------------------------------------------
# The settlement screen is the second half of the same flow. The result screen of a battle
# (VICTORY + 大获全胜 + 点击继续, the rank letter of BATTLE_STATUS_*) is followed by 大获全胜
# S/A/B/C/D + the EXP list of the fleet + 战斗记录 + 确定, whose rank letter is the recognition
# signal of EXP_INFO_* and whose 确定 is the button area of the same asset.
#
# AutoSearchCombat.auto_search_combat() skips that screen since 4e73027ce (handle_auto_search_exp_info,
# live 2026-09-22 02:56:34), but every other loop that can meet it knows only the first half: the
# page poll UI.ui_get_current_page() and the operation siren loops that call
# MapEventHandler.handle_map_event(). The screen is not the map - is_in_map() fails on it, measured
# on all 78 archived settlement frames - and it is not a page either, so such a loop polls its own
# buttons until the sixty second stuck check of the device ends the task:
#
#   * live 2026-09-26 22:46:39 alas2 OpsiHazard1Leveling, dump log/error/1790433999346. The task
#     entered the operation siren map, clicked the action point counter (ACTION_POINT_REMAIN_OS) in
#     action_point_enter(), handle_battle_result_screen() skipped the result screen that appeared
#     17 seconds later (its two clicks landed on the blue 战斗记录 button of the settlement layout,
#     which is the button area of BATTLE_STATUS_*), and the settlement screen that followed matched
#     no handler for sixty seconds -> GameStuckError: Wait too long.
#   * live 2025-12-19 03:10:40, same loop (action_point_enter), same screen, same error.
#   * 160 archived dumps reached the unknown page branch of the page poll and 7 of their frames are
#     this screen (2025-12-10, 2026-01-10 x2, 2026-06-10, 2026-08-28, 2026-08-29, 2026-09-18), all
#     `CRITICAL | Game page unknown`.
#   * further archived cases sit in os_auto_search_daemon (2025-12-23) and os_auto_search_quit
#     (2026-01-10).
#
# Recognition and localization both come from the assets, exactly like handle_auto_search_exp_info():
# the rank letter area is the recognition signal and the button area of the same asset is 确定. No
# string is matched anywhere on this path (every probe is a colour probe), so the OCR noise
# tolerance of the shipyard and dock paths does not apply here.
#
# page_main is the one screen whose random background is known to trigger these rank letters:
# upstream keeps the same probe out of OSMap.interrupt_auto_search() for that reason
# (module/os/map.py, "Random background from page_main may trigger EXP_INFO_*, don't check them"),
# and that loop reaches page_main by design. Both check buttons of page_main are therefore asked
# before the rank letters; missing a settlement screen because of them is the behaviour this handler
# had before it existed, while clicking into page_main would press an unrelated button.
# ---------------------------------------------------------------------------------------------

# Rank letters of the settlement screen, the same asset set the auto search loop uses.
SETTLEMENT_RANK_BUTTONS = (EXP_INFO_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D)

# Interval between two "skip the settlement screen" clicks, same as battle_result_click_timer.
settlement_click_timer = Timer(2, count=0)
# Clicks spent on the settlement screen that is on the display right now.
settlement_attempt = 0

# A settlement screen that no combat loop skipped is clicked at most this many times; a screen that
# the game ignores then keeps the task on its sixty second stuck check, which is the recovery this
# state had before this handler existed (twelve clicks of the device guard would only replace the
# GameStuckError of the archive with a GameTooManyClickError).
SETTLEMENT_MAX_ATTEMPT = 3


def match_settlement_button(image):
    """
    Detect the settlement screen of a battle that was fought in the operation siren.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        Button: The matched rank button, or None.
    """
    # A visible main page is never the settlement screen, and its random background is the one
    # screen known to trigger the rank letters (see the comment above).
    if MAIN_GOTO_FLEET.appear_on(image) or MAIN_GOTO_CAMPAIGN_WHITE.appear_on(image):
        return None

    for button in SETTLEMENT_RANK_BUTTONS:
        if button.appear_on(image):
            return button

    return None


def handle_settlement_screen(app):
    """
    Skip a settlement screen that is left on the display, so that a loop waiting for the map can
    see the map again.

    The screen is clicked through the button of the asset that recognized it, which is the 确定
    button, so no new template and no new screen layout is assumed here. A single click can be
    swallowed by the game, hence the repeated attempts; the count is bounded, because a screen the
    game refuses to close has to fall back to the sixty second stuck check of the device (the
    campaign loops reach GameTooManyClickError on that state, live 2026-03-01 01:45:10).

    Args:
        app: Alas or UI instance.

    Returns:
        bool: If clicked.
    """
    global settlement_attempt

    if not settlement_click_timer.reached():
        return False

    button = match_settlement_button(app.device.image)
    if button is None:
        settlement_attempt = 0
        return False

    if settlement_attempt >= SETTLEMENT_MAX_ATTEMPT:
        # Warned once: the loop that keeps meeting the screen calls this every screenshot.
        if settlement_attempt == SETTLEMENT_MAX_ATTEMPT:
            logger.warning(f'Unable to skip the settlement screen: {button}')
            settlement_attempt += 1
        return False

    settlement_attempt += 1
    logger.info(f'Skip settlement screen: {button}, attempt {settlement_attempt}')
    # Device.click() takes a Button and reads `button.button`, which is the 确定 button.
    app.device.click(button)
    settlement_click_timer.reset()
    return True


# ---------------------------------------------------------------------------------------------
# A combat that is still running is the other half of the same problem. The battle HUD is not a
# page either, so UI.ui_get_current_page() polls the page list while it is on the display and
# ends in GamePageUnknownError ten seconds later. It happens whenever the scheduler is restarted
# while a battle is running - exactly what the guard does when it finds a stopped scheduler.
# Measured over the archived dumps: 38 of the 160 `Starting from current page is not supported`
# dumps have a live battle HUD on their frame (2025-12-08 -> 2026-09-25, both profiles, 14
# different tasks, this incident is log/error/1790317301661 on alas2 Commission). 26 more dumps
# of the same signature carry a battle result screen, which is what handle_battle_result_screen()
# above already covers.
#
# The way out is the one ALAS already uses in OSFleet.interrupt_auto_search() for the same state
# (module/os/map.py: pause -> quit -> reconfirm, "in: Any, usually to be is_combat_executing"):
# click the PAUSE button of the battle HUD to open the pause menu, then the QUIT button of that
# menu, then the confirmation. No new asset and no new screen layout is assumed - the pause button
# is what Combat.is_combat_executing() recognizes and the quit assets are the ones
# Combat.handle_combat_quit() clicks.
# ---------------------------------------------------------------------------------------------

# Battle HUD themes of Combat.is_combat_executing(), same order and same probes (match_luma for
# every theme; the SERVER dependent colour branch of PAUSE is not repeated here, a live battle is
# recognized by the luma probe of PAUSE on cn/en as well).
COMBAT_HUD_BUTTONS = (PAUSE, PAUSE_New, PAUSE_Iridescent_Fantasy, PAUSE_Christmas, PAUSE_Neon, PAUSE_Cyber,
                      PAUSE_HolyLight, PAUSE_Pharaoh, PAUSE_Star, PAUSE_Nurse, PAUSE_Devil, PAUSE_Seaside,
                      PAUSE_Ninja, PAUSE_ShadowPuppetry, PAUSE_MaidCafe, PAUSE_Ancient, PAUSE_SpringInn,
                      PAUSE_ElvenVine, PAUSE_GildedReverie, PAUSE_AzureCore, PAUSE_OldeRoyal, PAUSE_YoRHa,
                      PAUSE_Ritual)

# QUIT buttons of the pause menu, same order and same probe as Combat.handle_combat_quit().
COMBAT_QUIT_BUTTONS = (QUIT, QUIT_New, QUIT_Iridescent_Fantasy, QUIT_Cyber, QUIT_Christmas, QUIT_Pharaoh,
                       QUIT_Nurse, QUIT_Seaside, QUIT_Ninja, QUIT_MaidCafe, QUIT_SpringInn,
                       QUIT_GildedReverie, QUIT_YoRHa, QUIT_Ritual)

# Interval between two clicks of the same button of this sequence. QUIT_RECONFIRM is asked more
# often, exactly like Combat.handle_combat_quit_reconfirm().
combat_hud_pause_timer = Timer(2, count=0)
combat_hud_quit_timer = Timer(2, count=0)
combat_hud_reconfirm_timer = Timer(1, count=0)
# Clicks spent on the battle that is on the display right now. Every click of the sequence
# counts, so a pause menu that never opens cannot spend the twelve click guard of the device on
# the PAUSE button (six clicks at the interval below stop the sequence after about twelve
# seconds, well inside the guard).
combat_hud_attempt = 0
# When the current battle was seen first, to stop clicking a battle that never ends.
combat_hud_seen_at = 0.

# A battle HUD that no combat loop finished is clicked at most this many times.
COMBAT_HUD_MAX_ATTEMPT = 6
# ... and for at most this long; after that the page poll reports the page again and the
# scheduler restarts the client, which is the recovery this state had before.
COMBAT_HUD_PATIENCE = 60


def match_combat_hud_button(image):
    """
    Detect the battle HUD of a combat that is running right now.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        Button: The matched PAUSE button, or None.
    """
    for button in COMBAT_HUD_BUTTONS:
        if button.match_luma(image, offset=(10, 10)):
            return button

    return None


def match_combat_quit_button(image):
    """
    Detect the QUIT button of the pause menu.

    Args:
        image (np.ndarray): Screenshot.

    Returns:
        Button: The matched QUIT button, or None.
    """
    for button in COMBAT_QUIT_BUTTONS:
        if button.match_luma(image, offset=(20, 20)):
            return button

    return None


def handle_combat_hud(app):
    """
    Leave a combat that is still running, so that the page poll can see a page again.

    The sequence is pause -> quit -> reconfirm, the one OSFleet.interrupt_auto_search() uses for
    the same state. It is asked in that order of visibility, not in that order of actions: the
    pause menu covers the pause button of the battle HUD, so the menu has to be recognized before
    the battle HUD is looked for.

    Args:
        app: Alas or UI instance.

    Returns:
        bool: If a click was sent.
    """
    global combat_hud_attempt, combat_hud_seen_at

    image = app.device.image
    quit_button = match_combat_quit_button(image)
    reconfirm = bool(QUIT_RECONFIRM.match_luma(image, offset=(20, 20)))
    pause = None if (quit_button is not None or reconfirm) else match_combat_hud_button(image)

    if quit_button is None and not reconfirm and pause is None:
        combat_hud_attempt = 0
        combat_hud_seen_at = 0.
        return False

    if combat_hud_seen_at == 0.:
        combat_hud_seen_at = monotonic()
    if monotonic() - combat_hud_seen_at > COMBAT_HUD_PATIENCE:
        if combat_hud_attempt:
            logger.warning(f'Combat has not ended for {COMBAT_HUD_PATIENCE}s, '
                           f'clicks on its battle HUD do not move the game on')
            combat_hud_attempt = 0
        return False
    if combat_hud_attempt >= COMBAT_HUD_MAX_ATTEMPT:
        return False

    # The pause menu is open: leave the battle. Combat.handle_combat_quit() and
    # Combat.handle_combat_quit_reconfirm() are bound to the Alas instance of the combat loops,
    # not to the UI instance that polls the page, so the same two probes are asked here.
    if quit_button is not None and combat_hud_quit_timer.reached():
        combat_hud_attempt += 1
        combat_hud_quit_timer.reset()
        logger.info(f'Combat is still running, quit it: {quit_button}, attempt {combat_hud_attempt}')
        app.device.click(quit_button)
        return True
    if reconfirm and combat_hud_reconfirm_timer.reached():
        combat_hud_attempt += 1
        combat_hud_reconfirm_timer.reset()
        logger.info(f'Combat is still running, confirm quitting it, attempt {combat_hud_attempt}')
        app.device.click(QUIT_RECONFIRM)
        return True

    # The battle HUD itself: open the pause menu.
    if pause is None or not combat_hud_pause_timer.reached():
        return False
    combat_hud_attempt += 1
    combat_hud_pause_timer.reset()
    logger.info(f'Combat is still running, pause it: {pause}, attempt {combat_hud_attempt}')
    app.device.click(pause)
    return True
