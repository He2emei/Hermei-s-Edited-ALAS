import unittest

from module.os.cl1 import can_run_cl1, get_cl1_yellow_coins_preserve, has_reached_cl1_meowfficer_threshold


class FakeConfig:
    OpsiHazard1Leveling_YellowCoinsPreserve = 10000

    def __init__(self, values=None):
        self.values = values or {}

    def cross_get(self, key, default):
        return self.values.get(key, default)


class CL1SettingsTest(unittest.TestCase):
    def test_cl1_requires_yellow_coins_above_the_fuel_line(self):
        self.assertTrue(can_run_cl1(10001, 10000))
        self.assertFalse(can_run_cl1(10000, 10000))

    def test_meowfficer_handoff_includes_exact_action_point_threshold(self):
        self.assertTrue(has_reached_cl1_meowfficer_threshold(4500, 4500))
        self.assertFalse(has_reached_cl1_meowfficer_threshold(4499, 4500))

    def test_yellow_coin_preserve_uses_hazard_leveling_setting(self):
        config = FakeConfig({
            'OpsiHazard1Leveling.OpsiHazard1Leveling.YellowCoinsPreserve': 50000,
        })

        self.assertEqual(get_cl1_yellow_coins_preserve(config), 50000)

    def test_yellow_coin_preserve_falls_back_to_generated_default(self):
        self.assertEqual(get_cl1_yellow_coins_preserve(FakeConfig()), 10000)

    def test_yellow_coin_preserve_is_never_negative(self):
        config = FakeConfig({
            'OpsiHazard1Leveling.OpsiHazard1Leveling.YellowCoinsPreserve': -1,
        })

        self.assertEqual(get_cl1_yellow_coins_preserve(config), 0)


if __name__ == '__main__':
    unittest.main()
