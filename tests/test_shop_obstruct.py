import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat.assets import GET_ITEMS_1, GET_SHIP
from module.shop.assets import SHOP_CLICK_SAFE_AREA
from module.shop.base import ShopBase


ROOT = Path(__file__).parents[1]
FRAME = ROOT / 'tests/fixtures/shop/medal_purple_bulin_reward.png'


class ImmediateTimer:
    def __init__(self, *args, **kwargs):
        pass

    def reached(self):
        return True

    def reset(self):
        return self


class ShopObstructionTest(unittest.TestCase):
    def _shop(self, image=None):
        shop = object.__new__(ShopBase)
        shop.device = SimpleNamespace(image=image, click=Mock(), stuck_record_add=Mock())
        shop.interval_timer = {}
        shop.handle_popup_confirm = Mock(return_value=False)
        return shop

    def test_real_purple_bulin_frame_uses_get_ship_exit_button(self):
        image = np.asarray(Image.open(FRAME).convert('RGB'))
        shop = self._shop(image)
        with patch('module.base.base.Timer', ImmediateTimer):
            self.assertTrue(ShopBase.shop_obstruct_handle(shop))

        shop.device.click.assert_called_once_with(GET_SHIP)
        self.assertTrue(GET_SHIP.match(image, offset=(20, 20)))
        self.assertEqual(tuple(GET_SHIP.button), (1000, 631, 1055, 689))

        old_target = SHOP_CLICK_SAFE_AREA.button
        self.assertEqual(tuple(old_target), (1051, 137, 1218, 179))
        old_center = ((old_target[0] + old_target[2]) // 2,
                      (old_target[1] + old_target[3]) // 2)
        self.assertFalse(
            GET_SHIP.button[0] <= old_center[0] <= GET_SHIP.button[2]
            and GET_SHIP.button[1] <= old_center[1] <= GET_SHIP.button[3])

    def test_general_item_and_lock_confirmation_paths_are_preserved(self):
        shop = self._shop()
        shop.appear = Mock(side_effect=lambda button, **_kwargs: button is GET_ITEMS_1)
        self.assertTrue(ShopBase.shop_obstruct_handle(shop))
        shop.device.click.assert_called_once_with(SHOP_CLICK_SAFE_AREA)

        shop = self._shop()
        shop.appear = Mock(return_value=False)
        shop.handle_popup_confirm.return_value = True
        self.assertTrue(ShopBase.shop_obstruct_handle(shop))
        shop.handle_popup_confirm.assert_called_once_with('SHOP_OBSTRUCT')
        shop.device.click.assert_not_called()

    def test_unknown_page_is_not_clicked(self):
        shop = self._shop()
        shop.appear = Mock(return_value=False)
        self.assertFalse(ShopBase.shop_obstruct_handle(shop))
        shop.handle_popup_confirm.assert_called_once_with('SHOP_OBSTRUCT')
        shop.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
