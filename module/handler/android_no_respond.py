from module.handler.assets import ANDROID_NO_RESPOND, ANDROID_NO_RESPOND_DARK
from module.logger import logger

# The dialog has two known appearances.  ANDROID_NO_RESPOND holds the light theme it was captured
# from; ANDROID_NO_RESPOND_DARK holds the dark theme of MuMu 12 (Android 12), which is what the
# four archived dumps of this workspace show (log/error/1787609445464, 1790190735862,
# 1790448290191, 1790469436812).  The light asset scores 0.10 on those frames and the dark one
# 1.00, against a threshold of 0.85 and a best unrelated frame of 0.40, so both are checked.
NO_RESPOND_BUTTONS = (ANDROID_NO_RESPOND, ANDROID_NO_RESPOND_DARK)


def handle_android_no_respond(app, interval=5):
    """
    Dismiss the Android "application not responding" dialog by clicking its 等待 (wait) row.

    The dialog is a modal system window of the emulator, not a page of the game and not the map.
    While it is on the display the system swallows every touch that would reach the game behind
    it, so a loop that keeps clicking its own button gets no answer at all and ends with the
    twelve click guard of the device, even though both its recognition and its localization are
    correct: live 2026-09-27 08:37:16 (dump log/error/1790469436812, profile alas2, task
    OpsiHazard1Leveling), where os_auto_search_quit() clicked AUTO_SEARCH_REWARD twelve times at
    (603..678, 606..639), all inside the button area (575, 598, 721, 646) of the reward panel,
    while the dialog covered the middle of the same frame.  The same signature is archived three
    more times (2026-08-25 06:10:45, 2026-09-24 03:12:15, 2026-09-27 02:44:50).

    `_handle_app_login()` already answered the dialog, but only there, and only with the light
    asset, so a task that was running when the app stopped responding had no handler at all.
    This function is the single implementation both paths use, so the recognition (the template of
    the wait icon, which is free of text and therefore of the dialog's locale) and the
    localization (the same asset's button, the icon of the 等待 row) stay the same everywhere.

    The click is counted by hand and sent with control_check=False, exactly as the login loop did:
    a dialog that cannot be dismissed still ends with the twelve click guard of the device instead
    of an endless click loop.

    Args:
        app: An Alas instance, anything with `appear` and `device`.
        interval (int): Seconds between two dismiss clicks, the system dialog needs a moment to
            disappear.

    Returns:
        bool: If the dialog was on the display and a dismiss click was sent.
    """
    for button in NO_RESPOND_BUTTONS:
        if app.appear(button, offset=(30, 30), interval=interval):
            logger.warning('Emulator no respond')
            app.device.click_record_add(button)
            app.device.click_record_check()
            app.device.click(button, control_check=False)
            return True

    return False
