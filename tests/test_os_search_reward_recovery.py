import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
from module.exception import RequestHumanTakeover
try:
    from module.handler import os_search_reward as recovery
except ImportError:
    recovery = None
ROOT = Path(__file__).parents[1]

def method(path, name, ns):
    tree = ast.parse(path.read_text(encoding='utf8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node]), str(path), 'exec'), ns)
    return ns[name]

class EntryIntegrationTest(unittest.TestCase):
    def test_unknown_search_reward_recovers_before_combat_detection(self):
        page = SimpleNamespace(name='os_map', check_button=object())
        main = SimpleNamespace(state='reward', ui_current=None)
        main.device = SimpleNamespace(has_cached_image=False, app_is_running=lambda:True,
            screenshot=lambda:setattr(main, 'frames', main.frames+1), get_orientation=Mock(),
            uninstall_minicap=Mock())
        main.frames = 0
        main.config = SimpleNamespace(SERVER='cn', Emulator_ControlMethod='MaaTouch',
            Emulator_ScreenshotMethod='ADB', task=SimpleNamespace(command='OpsiMeowfficerFarming'))
        main.ui_page_appear = lambda **kw: main.state == 'map'
        main.appear = Mock(return_value=False)
        main.match_template_color = Mock(return_value=False)
        main.appear_then_click = Mock(return_value=False)
        main.ui_additional = Mock(return_value=False)
        class Timer:
            def __init__(self, seconds, **kw): self.seconds=seconds
            def start(self): return self
            def reached(self): return self.seconds == 10 and main.frames >= 5
            def reset(self): return None
        reset = Mock()
        def recover(obj):
            self.assertIs(obj, main)
            main.state='map'
            return True
        ns = dict(Timer=Timer, run_once=lambda f:f, logger=Mock(),
            Page=SimpleNamespace(iter_pages=lambda:[page]),
            GameNotRunningError=RuntimeError, GamePageUnknownError=RuntimeError,
            RequestHumanTakeover=RequestHumanTakeover,
            handle_os_search_reward=Mock(side_effect=recover), reset_os_search_reward=reset)
        for key in ['handle_android_no_respond','handle_combat_hud','handle_battle_result_screen','handle_settlement_screen']:
            ns[key]=Mock(return_value=False)
        for key in ['STRATEGIC_SEARCH_POPUP_CHECK','POPUP_CANCEL','GOTO_MAIN','GOTO_MAIN_WHITE','RPG_HOME']:
            ns[key]=object()
        fn=method(ROOT/'module/ui/ui.py','ui_get_current_page',ns)
        self.assertIs(fn(main), page)
        ns['handle_combat_hud'].assert_not_called()
        ns['handle_os_search_reward'].assert_called_once_with(main)
        reset.assert_called_once_with(main)

    def test_map_event_fallback_handles_same_reward_without_entry_restart(self):
        main=SimpleNamespace(is_in_map=Mock(return_value=False),appear=Mock(return_value=False),
            device=SimpleNamespace(click=Mock()))
        recover=Mock(return_value=True)
        ns=dict(logger=Mock(),handle_os_search_reward=recover,reset_os_search_reward=Mock())
        for key in ['GET_ITEMS_1','GET_ITEMS_2','GET_ITEMS_3','GET_ADAPTABILITY',
                    'GET_MEOWFFICER_ITEMS_1','GET_MEOWFFICER_ITEMS_2','CLICK_SAFE_AREA']:
            ns[key]=object()
        fn=method(ROOT/'module/os_handler/map_event.py','handle_map_get_items',ns)
        self.assertTrue(fn(main))
        recover.assert_called_once_with(main)
        main.device.click.assert_not_called()
        main.is_in_map.return_value=True
        self.assertFalse(fn(main))
        ns['reset_os_search_reward'].assert_called_once_with(main)
        recover.reset_mock()
        main.is_in_map.return_value=False
        main.appear.side_effect=lambda button,**kw:button is ns['GET_ITEMS_1']
        self.assertTrue(fn(main))
        recover.assert_not_called()
        main.device.click.assert_called_once_with(ns['CLICK_SAFE_AREA'])

@unittest.skipIf(recovery is None, 'new recovery module not implemented')
class SearchRewardTest(unittest.TestCase):
    def frame(self, title=True, footer=True, shift=0):
        im=np.zeros((720,1280,3),dtype=np.uint8)
        for ok,name,x,y in [(title,'search_reward_title_cn.png',565+shift,204),
                            (footer,'search_reward_continue_cn.png',595,478)]:
            if ok:
                a=cv2.cvtColor(cv2.imread(str(ROOT/'assets/cn/os_handler'/name)),cv2.COLOR_BGR2RGB)
                im[y:y+a.shape[0],x:x+a.shape[1]]=a
        return im
    def main(self, command='OpsiMeowfficerFarming', server='cn'):
        first=self.frame()
        m=SimpleNamespace(config=SimpleNamespace(SERVER=server,task=SimpleNamespace(command=command)),
                          device=SimpleNamespace(image=first,screenshot=Mock(),sleep=Mock(),click=Mock()))
        return m
    def test_reader_requires_both_anchors_geometry_and_shape(self):
        self.assertIsNotNone(recovery.read_os_search_reward(self.frame()))
        for im in [self.frame(title=False),self.frame(footer=False),self.frame(shift=4),
                   np.zeros((719,1280,3),dtype=np.uint8),None]:
            self.assertIsNone(recovery.read_os_search_reward(im))
    def test_dimmed_modal_background_and_wrong_dtype_are_rejected(self):
        for image in [(self.frame().astype(np.float32)*.65).astype(np.uint8),
                      self.frame().astype(np.float32)]:
            self.assertIsNone(recovery.read_os_search_reward(image))
    def test_two_fresh_frames_are_required_and_click_is_matched_continue(self):
        m=self.main()
        with patch.object(recovery.time,'monotonic',return_value=100):
            self.assertTrue(recovery.handle_os_search_reward(m))
        self.assertEqual(m.device.screenshot.call_count,2)
        m.device.sleep.assert_called_once_with(.3)
        button=m.device.click.call_args[0][0]
        self.assertEqual(button.name,'OS_SEARCH_REWARD_CONTINUE')
        self.assertEqual(tuple(button.button),(595,478,690,499))
    def test_changed_second_frame_does_not_click(self):
        m=self.main()
        m.device.screenshot.side_effect=lambda:setattr(m.device,'image',self.frame(footer=False))
        self.assertFalse(recovery.handle_os_search_reward(m))
        m.device.click.assert_not_called()
    def test_foreign_server_task_and_unknown_command_do_not_click(self):
        for server,command in [('en','OpsiDaily'),('cn','Coalition'),('cn',''),('cn',None)]:
            m=self.main(command,server)
            self.assertFalse(recovery.handle_os_search_reward(m))
            m.device.click.assert_not_called()
            m.device.screenshot.assert_not_called()
    def test_three_click_limit_cooldown_and_known_map_reset(self):
        m=self.main()
        with patch.object(recovery.time,'monotonic',return_value=100):
            self.assertTrue(recovery.handle_os_search_reward(m))
        with patch.object(recovery.time,'monotonic',return_value=101):
            self.assertTrue(recovery.handle_os_search_reward(m))
        self.assertEqual(m.device.click.call_count,1)
        for t in [102.1,104.2]:
            with patch.object(recovery.time,'monotonic',return_value=t):
                self.assertTrue(recovery.handle_os_search_reward(m))
        with patch.object(recovery.time,'monotonic',return_value=106.3):
            with self.assertRaisesRegex(RequestHumanTakeover,'three'):
                recovery.handle_os_search_reward(m)
        self.assertEqual(m.device.click.call_count,3)
        recovery.reset_os_search_reward(m)
        with patch.object(recovery.time,'monotonic',return_value=108.4):
            self.assertTrue(recovery.handle_os_search_reward(m))
        self.assertEqual(m.device.click.call_count,4)
    def test_unknown_observation_does_not_reset_exhausted_budget(self):
        m=self.main()
        for t in [100,102.1,104.2]:
            with patch.object(recovery.time,'monotonic',return_value=t):
                recovery.handle_os_search_reward(m)
        m.device.image=self.frame(footer=False)
        self.assertFalse(recovery.handle_os_search_reward(m))
        m.device.image=self.frame()
        with patch.object(recovery.time,'monotonic',return_value=106.3):
            with self.assertRaises(RequestHumanTakeover): recovery.handle_os_search_reward(m)
        self.assertEqual(m.device.click.call_count,3)
    def test_crossmonth_takeover_preserves_configuration(self):
        m=self.main('OpsiCrossMonth')
        m.config.save=Mock()
        for t in [100,102.1,104.2]:
            with patch.object(recovery.time,'monotonic',return_value=t):
                recovery.handle_os_search_reward(m)
        with patch.object(recovery.time,'monotonic',return_value=106.3):
            with self.assertRaisesRegex(RequestHumanTakeover,'^Overdue OpsiCrossMonth cannot confirm the old Operation Siren map'):
                recovery.handle_os_search_reward(m)
        m.config.save.assert_not_called()

if __name__=='__main__': unittest.main()
