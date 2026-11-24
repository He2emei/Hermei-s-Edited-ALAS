"""Leave only the verified CN voice/resource settings page using native HOME."""
from module.base.button import Button
from module.exception import RequestHumanTakeover
from module.ui.assets import GOTO_MAIN
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM

SETTINGS_TITLE = Button(area=(116, 13, 178, 43), color=(255, 255, 255),
                        button=(116, 13, 178, 43),
                        file='./assets/cn/ui/SETTINGS_VOICE_TITLE.png')
SETTINGS_VOICE = Button(area=(197, 116, 313, 147), color=(255, 255, 255),
                        button=(197, 116, 313, 147),
                        file='./assets/cn/ui/SETTINGS_VOICE_CHECK.png')

def known_voice_settings(image):
    return (image is not None and image.shape == (720, 1280, 3)
            and SETTINGS_TITLE.match(image, offset=0, similarity=.95)
            and SETTINGS_VOICE.match(image, offset=0, similarity=.95))

def dismiss_known_voice_settings(app):
    if app.config.SERVER != 'cn':
        return False
    if not known_voice_settings(app.device.image):
        app._voice_settings_home_attempts = 0
        return False
    if not app.appear(GOTO_MAIN, offset=(20, 20)):
        return False
    app.device.screenshot()
    if not known_voice_settings(app.device.image):
        return True
    if app.appear(POPUP_CONFIRM, offset=(20, 20)) or app.appear(POPUP_CANCEL, offset=(20, 20)):
        raise RequestHumanTakeover('Verified settings page has an unknown dialog; no option will be changed')
    attempts = getattr(app, '_voice_settings_home_attempts', 0)
    if attempts >= 3:
        raise RequestHumanTakeover('Verified settings HOME did not respond after three attempts')
    if app.appear(GOTO_MAIN, offset=(20, 20), interval=2):
        app.device.click(GOTO_MAIN)
        app._voice_settings_home_attempts = attempts + 1
    return True
