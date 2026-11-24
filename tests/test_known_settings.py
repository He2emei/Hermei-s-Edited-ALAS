import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
import numpy as np
from module.ui.known_settings import known_voice_settings,dismiss_known_voice_settings,SETTINGS_TITLE,SETTINGS_VOICE
from module.ui.assets import GOTO_MAIN
from module.handler.assets import POPUP_CANCEL,POPUP_CONFIRM
from module.exception import RequestHumanTakeover

class KnownSettingsTest(unittest.TestCase):
    def frame(self):
        image=np.zeros((720,1280,3),dtype=np.uint8)
        for b in (SETTINGS_TITLE,SETTINGS_VOICE):
            x1,y1,x2,y2=b.area;ref=np.asarray(Image.open(b.file))
            image[y1:y2,x1:x2]=ref[y1:y2,x1:x2,:3]
        return image
    def app(self):
        app=SimpleNamespace(config=SimpleNamespace(SERVER='cn'),device=SimpleNamespace(image=self.frame(),screenshot=Mock(),click=Mock()))
        app.appear=Mock(side_effect=lambda b,**kwargs:b is GOTO_MAIN)
        return app
    def test_both_generic_titles_required(self):
        frame=self.frame();self.assertTrue(known_voice_settings(frame));frame[116:147,197:313]=0;self.assertFalse(known_voice_settings(frame))
    def test_two_frames_native_home_only(self):
        app=self.app();self.assertTrue(dismiss_known_voice_settings(app));app.device.screenshot.assert_called_once();app.device.click.assert_called_once_with(GOTO_MAIN)
    def test_changed_frame_consumed_without_click(self):
        app=self.app()
        with patch('module.ui.known_settings.known_voice_settings',side_effect=[True,False]):self.assertTrue(dismiss_known_voice_settings(app))
        app.device.click.assert_not_called()
    def test_foreign_unknown_and_no_home_do_not_click(self):
        app=self.app();app.config.SERVER='en'
        with patch('module.ui.known_settings.known_voice_settings') as reader:self.assertFalse(dismiss_known_voice_settings(app));reader.assert_not_called()
        app=self.app();app.device.image=np.zeros((720,1280,3),dtype=np.uint8);self.assertFalse(dismiss_known_voice_settings(app));app.device.click.assert_not_called()
        app=self.app();app.appear.return_value=False;app.appear.side_effect=None;self.assertFalse(dismiss_known_voice_settings(app));app.device.click.assert_not_called()
    def test_unknown_dialog_and_repeated_failure_takeover(self):
        app=self.app();app.appear.side_effect=lambda b,**kw:b is GOTO_MAIN or b is POPUP_CONFIRM
        with self.assertRaises(RequestHumanTakeover):dismiss_known_voice_settings(app)
        app.device.click.assert_not_called()
        app=self.app();app._voice_settings_home_attempts=3
        with self.assertRaises(RequestHumanTakeover):dismiss_known_voice_settings(app)
        app.device.click.assert_not_called()

if __name__=='__main__':unittest.main()
