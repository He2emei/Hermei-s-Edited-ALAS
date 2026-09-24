import unittest
from pathlib import Path

import cv2
import numpy as np

from module.os.deployment_cost import read_deployment_cost


class DeploymentCostTest(unittest.TestCase):
    def test_live_cn_confirmation_reads_free_cost(self):
        path = Path(__file__).parent / 'fixtures' / 'opsi_free_deployment_confirmation.png'
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        self.assertEqual(read_deployment_cost(image), 0)

    def test_unknown_screen_never_counts_as_free(self):
        self.assertIsNone(read_deployment_cost(np.zeros((720, 1280, 3), dtype=np.uint8)))


if __name__ == '__main__':
    unittest.main()
