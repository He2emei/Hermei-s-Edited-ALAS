import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.combat.combat import Combat
from tests.test_battle_result_skip import ClickContractDevice

ROOT = Path(__file__).parents[1]
HUD = np.asarray(Image.open(ROOT / 'tests/fixtures/combat_entry/boss-hud.png').convert('RGB'))


class CombatEntryApp:
    combat_appear = Combat.combat_appear
    is_combat_executing = Combat.is_combat_executing
    image_crop = ModuleBase.image_crop

    def __init__(self, frame=HUD, fleet_lock=True, in_map=False, loading=False):
        self.config = SimpleNamespace(Campaign_UseFleetLock=fleet_lock, SERVER='cn')
        self.device = ClickContractDevice(frame)
        self.device.stuck_record_add = Mock()
        self.in_map = in_map
        self.loading = Mock(return_value=loading)
        self.appear = Mock(return_value=False)
        self.handle_combat_automation_confirm = Mock(return_value=False)

    def is_in_map(self):
        return self.in_map

    def is_combat_loading(self):
        return self.loading()


class CombatEntryTest(unittest.TestCase):
    def test_real_boss_hud_is_recognized_after_loading_frame_was_missed(self):
        app = CombatEntryApp()
        self.assertTrue(app.combat_appear())
        app.loading.assert_called_once_with()

    def test_loading_remains_first_priority(self):
        app = CombatEntryApp(frame=np.zeros_like(HUD), loading=True)
        app.is_combat_executing = Mock(return_value=False)
        self.assertTrue(app.combat_appear())
        app.is_combat_executing.assert_not_called()

    def test_unknown_blank_frame_is_not_assumed_to_be_combat(self):
        app = CombatEntryApp(frame=np.zeros_like(HUD))
        self.assertFalse(app.combat_appear())

    def test_map_gate_does_not_accept_combat_hud(self):
        app = CombatEntryApp(in_map=True)
        self.assertFalse(app.combat_appear())

    def test_non_fleet_lock_behavior_does_not_probe_combat_hud(self):
        app = CombatEntryApp(fleet_lock=False)
        app.is_combat_executing = Mock(return_value=True)
        self.assertFalse(app.combat_appear())
        app.is_combat_executing.assert_not_called()
        app.loading.assert_not_called()

    def test_battle_preparation_is_still_recognized(self):
        app = CombatEntryApp()
        app.appear = Mock(side_effect=[True])
        app.is_combat_executing = Mock(return_value=False)
        self.assertTrue(app.combat_appear())
        app.is_combat_executing.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
