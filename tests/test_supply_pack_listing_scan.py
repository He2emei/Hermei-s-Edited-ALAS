import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from PIL import Image
from module.freebies.supply_pack import SupplyPack
from module.freebies.assets import FREE_SUPPLY_PACK

class WeeklyListingScanTest(unittest.TestCase):
    def manager(self,position=3,target=1):
        manager=object.__new__(SupplyPack)
        state={'position':position,'page':True,'swipes':[],'clears':0,'clicks':[]}
        image=np.zeros((720,1280,3),dtype=np.uint8)
        def refresh():image[180:665,195:1000]=state['position']*40
        def swipe(vector,**kwargs):
            state['swipes'].append(vector)
            state['position']=max(0,state['position']-2) if vector[0]>0 else min(4,state['position']+1)
            refresh()
        def clear():state['clears']+=1
        manager.device=SimpleNamespace(image=image,screenshot=refresh,swipe_vector=swipe,sleep=lambda _:None,click_record_clear=clear,click=lambda x:state['clicks'].append(x))
        manager.match_template_color=lambda *a,**k:state['page']
        manager.appear=lambda *a,**k:state['position']==target
        refresh()
        return manager,state
    def test_real_scanner_resets_remembered_position_and_small_steps_find_skipped_card(self):
        manager,state=self.manager()
        self.assertTrue(manager._scan_weekly_free_price())
        self.assertTrue(any(x[0]>0 for x in state['swipes']))
        self.assertIn((-150,0),state['swipes'])
        self.assertEqual(state['clicks'],[FREE_SUPPLY_PACK])
    def test_no_target_is_bounded_and_stationary_gesture_does_not_clear_history(self):
        manager,state=self.manager(target=99)
        self.assertFalse(manager._scan_weekly_free_price(max_swipes=24))
        self.assertLessEqual(len(state['swipes']),28)
        self.assertLess(state['clears'],len(state['swipes']))
        self.assertEqual(state['clicks'],[])
    def test_unknown_page_and_zero_swipe_bound_make_no_gesture(self):
        manager,state=self.manager(target=99);state['page']=False
        self.assertFalse(manager._scan_weekly_free_price());self.assertFalse(state['swipes'])
        state['page']=True
        self.assertFalse(manager._scan_weekly_free_price(max_swipes=0));self.assertFalse(state['swipes'])
    def test_candidate_disappearing_between_frames_never_opens_preview(self):
        manager,state=self.manager(position=1)
        manager.device.screenshot=lambda:state.update(position=2)
        self.assertFalse(manager._open_stable_weekly_candidate());self.assertEqual(state['clicks'],[])
    def test_page_changes_during_candidate_check_make_no_followup_gesture(self):
        manager,state=self.manager(position=1)
        manager.device.screenshot=lambda:state.update(page=False)
        self.assertFalse(manager._scan_weekly_free_price())
        self.assertEqual(state['clicks'],[]);self.assertEqual(state['swipes'],[])
    def test_price_ocr_locator_only_opens_preview_after_two_matching_free_labels(self):
        manager,state=self.manager(target=99)
        manager.device.image=np.asarray(Image.open(Path(__file__).parent/'fixtures/supply_pack/current-paid-listing.png').convert('RGB'))
        manager.device.screenshot=Mock()
        with patch('module.freebies.supply_pack.Ocr.ocr',return_value='免费'):
            self.assertTrue(manager._open_stable_weekly_candidate())
        self.assertEqual(len(state['clicks']),1)
        self.assertEqual(state['clicks'][0].name,'WEEKLY_FREE_PRICE_LABEL')
        state['clicks'].clear()
        answers=iter(['免费']+['400']*10)
        with patch('module.freebies.supply_pack.Ocr.ocr',side_effect=lambda *a,**k:next(answers)):
            self.assertFalse(manager._open_stable_weekly_candidate())
        self.assertEqual(state['clicks'],[])
    def test_actual_paid_listing_has_no_free_candidate(self):
        manager,state=self.manager(target=99)
        manager.device.image=np.asarray(Image.open(Path(__file__).parent/'fixtures/supply_pack/current-paid-listing.png').convert('RGB'))
        self.assertIsNone(manager._weekly_free_price_candidate());self.assertEqual(state['clicks'],[])

if __name__=='__main__':unittest.main()
