import unittest

from module.dorm.training_policy import (
    decide_dorm_trainability,
    plan_dorm_rotation,
    should_awaken_in_dorm,
)
from module.os.training_policy import ShipCandidate, decide_trainability


def ship(name, position='submarine', level=90, rainbow=False, broken=True,
         stored=0, cap=120, is_locked=True):
    return ShipCandidate(name, '皇家', position, level, rainbow, broken, stored, cap, is_locked)


class DormTrainingPolicyTest(unittest.TestCase):
    def test_existing_125_cap_can_gain_exp_without_permission_for_new_awakening_ii(self):
        from module.dorm.training_policy import decide_dorm_trainability
        for level in (120, 124):
            candidate = ship('already-awakened', level=level, stored=0, cap=125)
            self.assertTrue(decide_dorm_trainability(candidate).allowed)
            self.assertFalse(should_awaken_in_dorm(candidate))
        self.assertFalse(decide_dorm_trainability(ship('done', level=125, cap=125)).allowed)

    def test_submarine_position_is_valid_for_shared_trainability(self):
        self.assertTrue(decide_trainability(ship('u', level=109, stored=0, cap=120)).allowed)

    def test_dorm_policy_ignores_shared_completed_xp_stop_below_120(self):
        for cap in (110, 115):
            with self.subTest(cap=cap):
                candidate = ship('u', level=cap, stored=3_000_000, cap=cap)
                self.assertFalse(decide_trainability(candidate).allowed)
                self.assertTrue(decide_dorm_trainability(candidate).allowed)

    def test_dorm_policy_fails_closed_on_unknown_cap_or_required_exp(self):
        self.assertFalse(decide_dorm_trainability(ship('u', level=99, stored=0, cap=None)).allowed)
        self.assertFalse(decide_dorm_trainability(ship('u', level=110, stored=None, cap=110)).allowed)

    def test_dorm_policy_rejects_unlocked_and_unbroken_ordinary_subs_at_cap_or_100(self):
        self.assertFalse(decide_dorm_trainability(ship('u', is_locked=False)).allowed)
        self.assertFalse(decide_dorm_trainability(ship('u', level=70, broken=False, cap=70)).allowed)

    def test_dorm_policy_keeps_unbroken_low_level_subs_until_their_cap(self):
        self.assertTrue(decide_dorm_trainability(ship('u', level=3, broken=False, cap=70)).allowed)
        self.assertTrue(decide_dorm_trainability(ship('u', level=69, broken=False, cap=70)).allowed)
        capped = decide_dorm_trainability(ship('u', level=70, broken=False, cap=70))
        self.assertFalse(capped.allowed)
        self.assertIn('limit break is required', capped.reason)
        self.assertFalse(decide_dorm_trainability(ship('u', level=100, broken=False, cap=100)).allowed)

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

    def test_level_120_and_125_submarines_are_replaced(self):
        for level, cap, stored in ((120, 120, 0), (125, 125, 3_000_000)):
            with self.subTest(level=level):
                current = {1: ship('done', level=level, stored=stored, cap=cap), 2: None}
                plan = plan_dorm_rotation(current, [ship('a'), ship('b')], 2)
                self.assertTrue(plan.success)
                self.assertEqual({plan.slots[1].name, plan.slots[2].name}, {'a', 'b'})

    def test_partial_rotation_retains_unreplaced_completed_sub_and_surface_ship(self):
        current = {
            1: ship('done', level=120, stored=0, cap=120),
            2: ship('surface', position='main', level=80, cap=None),
            3: None,
        }
        plan = plan_dorm_rotation(current, [ship('only')], 3, allow_partial=True)
        self.assertTrue(plan.success)
        self.assertEqual(plan.slots[1].name, 'done')
        self.assertEqual(plan.slots[2].name, 'surface')
        self.assertEqual(plan.slots[3].name, 'only')

    def test_partial_rotation_fails_when_candidate_shortage_leaves_vacancy(self):
        current = {1: None, 2: None}
        plan = plan_dorm_rotation(current, [ship('only')], 2, allow_partial=True)
        self.assertFalse(plan.success)
        self.assertIsNone(plan.slots[1])
        self.assertIsNone(plan.slots[2])

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
