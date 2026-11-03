import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from PIL import Image
from module.shop.shop_medal import MedalShop2_250814
from module.shop.medal_monthly_policy import priority

class MedalBlueprintFrameTest(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).parent/'fixtures'/'medal_monthly'
        self.frames=[np.asarray(Image.open(base/('blueprints-%d.png'%n)).convert('RGB')) for n in (1,2)]
        self.shop=object.__new__(MedalShop2_250814)
        self.shop.device=SimpleNamespace(image=self.frames[0],screenshot=lambda:setattr(self.shop.device,'image',self.frames[1]))
        self.shop._monthly_clear_active_rank=3
        self.shop._monthly_clear_metadata_blocked=False
    def test_actual_shared_template_is_split_by_independent_two_frame_rarity_and_title(self):
        self.assertEqual(priority('DRS5'),3)
        for button,rank in (((941,239,1005,303),3),((265,462,329,526),9)):
            self.shop.device.image=self.frames[0]
            self.assertEqual(self.shop._monthly_item_rank(SimpleNamespace(name='DRS5',button=button)),rank)
    def test_blank_title_unknown_color_and_changed_second_frame_fail_closed(self):
        item=SimpleNamespace(name='DRS5',button=(265,462,329,526))
        blank=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertIsNone(self.shop._monthly_blueprint_frame_rank(item,blank))
        changed=self.frames[1].copy();changed[465:470,268:273]=[40,190,245]
        self.shop.device.screenshot=lambda:setattr(self.shop.device,'image',changed)
        self.assertIsNone(self.shop._monthly_item_rank(item))
        self.assertTrue(self.shop._monthly_clear_metadata_blocked)
        self.assertIsNone(self.shop._monthly_blueprint_frame_rank(item,np.zeros((10,10,3),dtype=np.uint8)))

if __name__=='__main__':unittest.main()
