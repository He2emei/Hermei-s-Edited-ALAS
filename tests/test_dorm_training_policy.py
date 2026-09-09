import unittest

from module.dorm.training_policy import plan_dorm_rotation, should_awaken_in_dorm
from module.os.training_policy import ShipCandidate, decide_trainability


def ship(name, position='submarine', level=90, rainbow=False, broken=True,
         stored=None, cap=None):
    return ShipCandidate(name, '皇家', position, level, rainbow, broken, stored, cap)


class DormTrainingPolicyTest(unittest.TestCase):
    def test_submarine_position_is_valid_for_shared_trainability(self):
        self.assertTrue(decide_trainability(ship('u', level=109, stored=0, cap=120)).allowed)

    def test_awaken_caps_allow_trainable_submarines_but_not_120_or_125(self):
        for cap in (100, 105, 110, 115):
            with self.subTest(cap=cap):
                self.assertTrue(should_awaken_in_dorm(ship('u', level=cap, stored=0, cap=cap)))
        self.assertFalse(should_awaken_in_dorm(ship('u', level=120, stored=0, cap=120)))
        self.assertFalse(should_awaken_in_dorm(ship('u', level=125, stored=3_000_000, cap=125)))

    def test_awaken_keeps_full_break_and_rainbow_rules(self):
        self.assertFalse(should_awaken_in_dorm(ship('u', level=100, stored=0, cap=100, broken=False)))
        self.assertTrue(should_awaken_in_dorm(ship('u', level=100, stored=0, cap=100, rainbow=True, broken=False)))

    def test_rotation_preserves_trainable_subs_and_non_subs(self):
        current = {1: ship('keep', level=109, stored=0, cap=120),
                   2: ship('surface', position='main', level=80, cap=None)}
        plan = plan_dorm_rotation(current, [ship('new')], 2)
        self.assertTrue(plan.success)
        self.assertEqual(plan.slots[1].name, 'keep')
        self.assertEqual(plan.slots[2].name, 'surface')

    def test_bad_submarine_and_empty_slot_are_replaced_atomically(self):
        current = {1: ship('done', level=125, stored=3_000_000, cap=125), 2: None}
        plan = plan_dorm_rotation(current, [ship('a'), ship('b')], 2)
        self.assertTrue(plan.success)
        self.assertEqual({plan.slots[1].name, plan.slots[2].name}, {'a', 'b'})

    def test_insufficient_replacements_fail_without_partial_plan(self):
        current = {1: ship('done', level=125, stored=3_000_000, cap=125), 2: None}
        plan = plan_dorm_rotation(current, [ship('only')], 2)
        self.assertFalse(plan.success)
        self.assertIsNone(plan.slots[2])
        self.assertEqual(plan.slots[1].name, 'done')

    def test_rotation_rejects_duplicate_identity(self):
        duplicate = ship('same')
        plan = plan_dorm_rotation({1: duplicate, 2: duplicate}, [], 2)
        self.assertFalse(plan.success)

    def test_capacity_is_limited_to_one_through_six(self):
        plan = plan_dorm_rotation({}, [], 7)
        self.assertFalse(plan.success)


if __name__ == '__main__':
    unittest.main()
