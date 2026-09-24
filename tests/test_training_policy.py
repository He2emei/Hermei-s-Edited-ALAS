import unittest

from module.os.training_policy import (
    ShipCandidate,
    TrainingRequirement,
    decide_awaken,
    decide_trainability,
    parse_training_requirement,
    plan_rotation,
)


def ship(name='A', faction='皇家', position='main', level=100,
         rainbow=False, broken=True, stored=0, cap=100):
    return ShipCandidate(name, faction, position, level, rainbow, broken, stored, cap)


class TrainingPolicyTest(unittest.TestCase):
    def test_later_current_ship_cannot_duplicate_an_earlier_assignment(self):
        current = {2: ship('done', level=125, cap=125), 3: ship('shared'),
                   5: ship('v1', position='vanguard'), 6: ship('v2', position='vanguard')}
        plan = plan_rotation({}, current, [ship('shared'), ship('spare')])
        self.assertTrue(plan.success)
        identities = [plan.slots[i].identity for i in (2, 3, 5, 6)]
        self.assertEqual(len(identities), len(set(identities)))

    def test_parse_roman_variants_and_explicit_faction_union(self):
        first = parse_training_requirement('皇家 先锋技术测试Ⅰ')
        second = parse_training_requirement('皇家/白鹰主力技术测试 II')
        self.assertEqual(first.factions, frozenset({'皇家'}))
        self.assertEqual(first.position, 'vanguard')
        self.assertEqual(first.stage, 1)
        self.assertEqual(second.factions, frozenset({'皇家', '白鹰'}))
        self.assertEqual(second.position, 'main')
        self.assertEqual(second.stage, 2)
        with self.assertRaises(ValueError):
            parse_training_requirement('未知先锋技术测试I')

    def test_level_125_and_full_break_anchors(self):
        self.assertFalse(decide_trainability(ship(level=125, cap=125)).allowed)
        self.assertIn('125', decide_trainability(ship(level=125, cap=125)).reason)
        decision = decide_trainability(ship(level=100, broken=False))
        self.assertFalse(decision.allowed)
        self.assertIn('limit broken', decision.reason)

    def test_rainbow_is_exempt_from_full_break(self):
        self.assertTrue(decide_trainability(ship(rainbow=True, broken=False, stored=0)).allowed)
        self.assertTrue(decide_trainability(ship(level=119, cap=120, rainbow=True)).allowed)
        self.assertFalse(decide_trainability(ship(level=120, cap=120, rainbow=True, stored=0)).allowed)

    def test_stored_exp_is_required_and_threshold_completes(self):
        self.assertFalse(decide_trainability(ship(level=105, stored=None)).allowed)
        self.assertTrue(decide_trainability(ship(level=109, stored=2_999_999, cap=120)).allowed)
        self.assertFalse(decide_trainability(ship(level=110, stored=3_000_000, cap=110)).allowed)
        self.assertTrue(decide_trainability(ship(level=115, rainbow=True, stored=3_000_000, cap=115)).allowed)

    def test_intermediate_116_is_not_implicitly_complete(self):
        self.assertTrue(decide_trainability(ship(level=116, stored=None, cap=120)).allowed)
        self.assertFalse(decide_trainability(ship(level=116, stored=3_000_000, cap=116)).allowed)
        self.assertFalse(decide_trainability(ship(level=116, stored=0, cap=None)).allowed)
        self.assertTrue(decide_trainability(ship(level=90, stored=None, cap=None)).allowed)

    def test_malformed_boolean_and_level_caps_are_rejected(self):
        self.assertFalse(decide_trainability(ship(rainbow=None)).allowed)
        self.assertFalse(decide_trainability(ship(broken=None)).allowed)
        self.assertFalse(decide_trainability(ship(level=True)).allowed)
        self.assertFalse(decide_trainability(ship(level=100, cap=99)).allowed)
        self.assertFalse(decide_trainability(ship(level=100, cap=126)).allowed)

    def test_awaken_caps_and_no_120_to_125(self):
        self.assertTrue(decide_awaken(ship(level=100, cap=100)).allowed)
        self.assertFalse(decide_awaken(ship(level=99, cap=100)).allowed)
        self.assertTrue(decide_awaken(ship(level=115, cap=115, rainbow=True)).allowed)
        self.assertFalse(decide_awaken(ship(level=120, cap=120)).allowed)
        self.assertFalse(decide_awaken(ship(level=110, cap=110)).allowed)

    def test_rotation_preserves_current_and_uses_screen_order(self):
        requirement = TrainingRequirement(frozenset({'皇家'}), 'main', 1, 'test')
        current = ship('current', level=100)
        first = ship('first', level=100)
        second = ship('second', level=100)
        current_slots = {
            1: ship('fixed'), 2: current, 3: ship('cur3'),
            5: ship('cur5', position='vanguard'), 6: ship('cur6', position='vanguard'),
        }
        plan = plan_rotation({2: requirement}, current_slots, [first, second])
        self.assertTrue(plan.success)
        self.assertEqual(plan.slots[2].identity, 'current')

        plan = plan_rotation(
            {2: requirement},
            {},
            [first, second, ship('v1', position='vanguard'), ship('v2', position='vanguard')],
        )
        self.assertEqual(plan.slots[2].identity, 'first')

    def test_rotation_is_side_restricted_atomic_and_deduplicated(self):
        main = TrainingRequirement(frozenset({'皇家'}), 'main', 1, 'main')
        vanguard = TrainingRequirement(frozenset({'皇家'}), 'vanguard', 1, 'vanguard')
        only_one = ship('one', position='main')
        plan = plan_rotation({2: main, 3: main}, {}, [only_one])
        self.assertFalse(plan.success)
        self.assertIn('cannot be satisfied', plan.reason)

        cross_side = ship('v', position='vanguard')
        plan = plan_rotation({2: main}, {}, [cross_side])
        self.assertFalse(plan.success)

        plan = plan_rotation({2: main, 5: vanguard}, {},
                             [ship('main'), ship('v', position='vanguard')],
                             excluded_identities={'main'})
        self.assertFalse(plan.success)

    def test_none_requirements_still_fill_all_four_slots_with_trainable_ships(self):
        candidates = [ship('m1'), ship('m2'), ship('v1', position='vanguard'),
                      ship('v2', position='vanguard')]
        plan = plan_rotation({2: None, 3: None, 5: None, 6: None},
                             {1: ship('fixed'), 4: ship('fixed2')}, candidates)
        self.assertTrue(plan.success)
        self.assertEqual(set(plan.slots), {1, 2, 3, 4, 5, 6})
        self.assertEqual(plan.slots[1].identity, 'fixed')
        self.assertEqual(plan.slots[4].identity, 'fixed2')
        self.assertEqual({plan.slots[2].identity, plan.slots[3].identity}, {'m1', 'm2'})
        self.assertEqual({plan.slots[5].identity, plan.slots[6].identity}, {'v1', 'v2'})

    def test_unrestricted_side_accepts_catalogued_meta_and_collab_factions(self):
        candidates = [ship('meta', faction='META'), ship('collab', faction='联动'),
                      ship('v1', position='vanguard'), ship('v2', position='vanguard')]
        plan = plan_rotation({2: None, 3: None, 5: None, 6: None}, {}, candidates)
        self.assertTrue(plan.success)
        self.assertEqual({plan.slots[2].identity, plan.slots[3].identity}, {'meta', 'collab'})
        self.assertFalse(plan_rotation({2: None}, {}, [ship('unknown', faction='未知')]).success)

    def test_rainbow_and_faction_share_required_side_when_possible(self):
        requirement = TrainingRequirement(frozenset({'皇家'}), 'vanguard', 1, '皇家先锋技术测试I')
        current = {2: ship('ordinary-main'), 3: ship('other-main'),
                   5: ship('ordinary-vanguard', faction='重樱', position='vanguard'),
                   6: ship('other-vanguard', faction='重樱', position='vanguard')}
        candidates = [
            ship('rainbow-main', rainbow=True, level=115, cap=115),
            ship('rainbow-vanguard', faction='重樱', position='vanguard', rainbow=True, level=115, cap=115),
            ship('royal-vanguard', position='vanguard'),
            ship('royal-rainbow', position='vanguard', rainbow=True, level=115, cap=115),
        ]
        plan = plan_rotation({5: requirement, 6: requirement}, current, candidates)
        self.assertTrue(plan.success)
        self.assertEqual({plan.slots[5].name, plan.slots[6].name}, {'royal-vanguard', 'royal-rainbow'})
        self.assertIn('rainbow-main', {plan.slots[2].name, plan.slots[3].name})

    def test_unmatched_rainbow_and_one_faction_take_priority(self):
        requirement = TrainingRequirement(frozenset({'皇家'}), 'vanguard', 1, '皇家先锋技术测试I')
        current = {2: ship('main1'), 3: ship('main2'),
                   5: ship('current-rainbow', faction='重樱', position='vanguard',
                           rainbow=True, level=115, cap=115),
                   6: ship('current-royal', position='vanguard')}
        plan = plan_rotation({5: requirement, 6: requirement}, current,
                             [ship('other-royal', position='vanguard')])
        self.assertTrue(plan.success)
        self.assertEqual(plan.slots[5].name, 'current-rainbow')
        self.assertEqual(plan.slots[6].name, 'current-royal')


if __name__ == '__main__':
    unittest.main()
