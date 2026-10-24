import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.os.training import TrainingFleetManager
from module.os.training_policy import ShipCandidate
from module.os.training_policy import TrainingRequirement


class TrainingRainbowPriorityTest(unittest.TestCase):
    def test_maintain_fills_both_rainbows_after_faction_shortage_and_searches_unrestricted_side(self):
        def ship(name, side='main', rainbow=True, faction='皇家'):
            return ShipCandidate(name, faction, side, 90, rainbow, True, 0, 100, True)

        royal = ship('royal-rainbow')
        foreign = ship('foreign-rainbow', faction='重樱')
        storage = ShipCandidate('storage', '皇家', 'main', 110, False, True, 927712, 110, True)
        requirement = TrainingRequirement(frozenset({'皇家'}), 'main', 1, '皇家主力技术测试I')
        for first, active, pool in ((ship('ordinary', rainbow=False), requirement, [royal, foreign]),
                                    (royal, None, [foreign])):
            with self.subTest(existing=first.name, faction_required=active is not None):
                current = {1: ship('anchor'), 2: first, 3: storage,
                           4: ship('anchor-front', side='vanguard'),
                           5: ship('front-1', side='vanguard'), 6: ship('front-2', side='vanguard')}
                manager = TrainingFleetManager.__new__(TrainingFleetManager)
                manager.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                    PriorityTraining_Ships='', PriorityTraining_Allow125Awakening=False,
                    cross_set=Mock())
                manager.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                manager._check_cn = Mock()
                manager.ui_ensure = Mock()
                manager.inspect_map_fleet = Mock(return_value=current)
                manager._available_ships = Mock(return_value={s.name for s in pool})
                manager._deploy = Mock()
                calls = []

                def find(side, factions, excluded, needed=2, **kwargs):
                    calls.append((side, factions, set(excluded), kwargs))
                    return [s for s in pool if s.position == side and s.name not in excluded
                            and (not factions or s.faction in factions)][:needed]

                manager.find_candidates = find
                opsi = SimpleNamespace(os_init=Mock(), globe_goto=Mock(), name_to_zone=lambda s: s)
                with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
                    shipyard.return_value.inspect_current_project.return_value = ('project', active)
                    manager.maintain(opsi)
                planned = manager._deploy.call_args[0][2]
                self.assertEqual({planned[2].name, planned[3].name}, {royal.name, foreign.name})
                self.assertEqual(planned[1], current[1])
                self.assertEqual(planned[4], current[4])
                ultra = [c for c in calls if c[0] == 'main' and c[3].get('rarity') == 'ultra']
                self.assertTrue(ultra)
                if active:
                    self.assertEqual(len(ultra), 2)
                    self.assertIn(royal.name, ultra[1][2])
                    self.assertFalse(ultra[1][1])

    def test_maintain_falls_back_to_unrestricted_second_ur_search(self):
        priority = ShipCandidate('虎', '皇家', 'main', 119, True, False, 0, 120, True)
        ordinary = ShipCandidate('皇家普通', '皇家', 'main', 90, False, True, 0, 100, True)
        cross_faction = ShipCandidate('重樱彩船', '重樱', 'main', 90, True, False, 0, 100, True)
        current = {
            1: ShipCandidate('英仙座', '皇家', 'main', 125, False, True, 0, 125),
            2: priority, 3: ordinary,
            4: ShipCandidate('伊吹', '重樱', 'vanguard', 125, False, True, 0, 125),
            5: ShipCandidate('先锋甲', '皇家', 'vanguard', 90, False, True, 0, 100),
            6: ShipCandidate('先锋乙', '皇家', 'vanguard', 90, False, True, 0, 100),
        }

        class Manager(TrainingFleetManager):
            def __init__(self):
                self.config = SimpleNamespace(SERVER='cn', OpsiFleet_Fleet=4,
                                              PriorityTraining_Ships='虎',
                                              PriorityTraining_Allow125Awakening=False,
                                              cross_set=lambda **kwargs: None)
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.calls = []
                self.plan = None

            def _check_cn(self): pass
            def ui_ensure(self, page): pass
            def inspect_map_fleet(self, opsi): return current
            def _available_ships(self, opsi, priority_names=()): return {'重樱彩船'}
            def find_candidates(self, side, factions, excluded, **kwargs):
                self.calls.append((side, factions, set(excluded), kwargs))
                if side == 'main' and kwargs.get('rarity') == 'ultra':
                    return [cross_faction] if not factions and cross_faction.name not in excluded else []
                return []
            def _deploy(self, opsi, before, planned): self.plan = planned

        opsi = SimpleNamespace(os_init=lambda **kwargs: None,
                               globe_goto=lambda *args: None,
                               name_to_zone=lambda name: name)
        requirement = TrainingRequirement(frozenset({'皇家'}), 'main', 1, '皇家主力技术测试I')
        with patch('module.shipyard.development.ShipyardDevelopment') as shipyard:
            shipyard.return_value.inspect_current_project.return_value = ('柴郡', requirement)
            manager = Manager()
            manager.maintain(opsi)

        ultra_calls = [call for call in manager.calls
                       if call[0] == 'main' and call[3].get('rarity') == 'ultra']
        self.assertEqual(len(ultra_calls), 2)
        self.assertTrue(ultra_calls[0][1])
        self.assertFalse(ultra_calls[1][1])
        self.assertIn('重樱彩船', {manager.plan[2].name, manager.plan[3].name})
        self.assertIn('虎', {manager.plan[2].name, manager.plan[3].name})
        self.assertEqual(manager.plan[1], current[1])
        self.assertEqual(manager.plan[4], current[4])


if __name__ == '__main__':
    unittest.main()
