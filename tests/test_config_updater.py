import unittest

from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get


class ConfigUpdaterTest(unittest.TestCase):
    def test_opsi_training_last_check_survives_reload(self):
        updater = ConfigUpdater()
        old = {
            'OpsiHazard1Leveling': {
                'OpsiTraining': {
                    'Enable': True,
                    'CheckIntervalMinutes': 60,
                    'LastCheck': 1789442139,
                },
            },
        }

        reloaded = updater.config_update(old)

        last_check = deep_get(reloaded, 'OpsiHazard1Leveling.OpsiTraining.LastCheck')
        self.assertIs(type(last_check), int)
        self.assertEqual(last_check, 1789442139)
        self.assertTrue(deep_get(reloaded, 'OpsiHazard1Leveling.OpsiTraining.Enable'))
        self.assertEqual(
            deep_get(reloaded, 'OpsiHazard1Leveling.OpsiTraining.CheckIntervalMinutes'),
            60,
        )

    def test_opsi_training_last_check_zero_initializes(self):
        old = {
            'OpsiHazard1Leveling': {
                'OpsiTraining': {
                    'LastCheck': 0,
                },
            },
        }

        reloaded = ConfigUpdater().config_update(old)

        self.assertEqual(
            deep_get(reloaded, 'OpsiHazard1Leveling.OpsiTraining.LastCheck'),
            0,
        )


if __name__ == '__main__':
    unittest.main()
