import unittest
from types import SimpleNamespace

from module.base.priority_training import allow_priority_125, priority_ship_names


class PriorityTrainingConfigTest(unittest.TestCase):
    def test_ordered_exact_names_and_delimiters(self):
        config = SimpleNamespace(PriorityTraining_Ships='虎 > 安土\n虎, 安土，天城')
        self.assertEqual(priority_ship_names(config), ('虎', '安土', '天城'))
        self.assertEqual(priority_ship_names(SimpleNamespace()), ())

    def test_invalid_config_and_explicit_boolean_gate(self):
        with self.assertRaises(ValueError):
            priority_ship_names(SimpleNamespace(PriorityTraining_Ships=['虎']))
        config = SimpleNamespace(PriorityTraining_Ships='虎', PriorityTraining_Allow125Awakening=1)
        self.assertFalse(allow_priority_125(config, '虎'))
        config.PriorityTraining_Allow125Awakening = True
        self.assertTrue(allow_priority_125(config, '虎'))
        self.assertFalse(allow_priority_125(config, '安土'))

