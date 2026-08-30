import sys
import unittest
from types import ModuleType, SimpleNamespace

# Keep this behavior test independent from ShipyardUI's image/OCR dependencies.
shipyard_ui = ModuleType('module.shipyard.ui')
shipyard_ui.ShipyardUI = type('ShipyardUI', (), {})
original_shipyard_ui = sys.modules.get('module.shipyard.ui')
original_ui_page = sys.modules.get('module.ui.page')
sys.modules['module.shipyard.ui'] = shipyard_ui
ui_page = ModuleType('module.ui.page')
ui_page.page_main = object()
ui_page.page_shipyard = object()
sys.modules['module.ui.page'] = ui_page
from module.shipyard.shipyard_reward import RewardShipyard
if original_shipyard_ui is None:
    del sys.modules['module.shipyard.ui']
else:
    sys.modules['module.shipyard.ui'] = original_shipyard_ui
if original_ui_page is None:
    del sys.modules['module.ui.page']
else:
    sys.modules['module.ui.page'] = original_ui_page


class ZeroSelectionHarness:
    _shipyard_buy = RewardShipyard._shipyard_buy
    _shipyard_use = RewardShipyard._shipyard_use
    _shipyard_bp_rarity = 'DR'

    def __init__(self):
        self.config = SimpleNamespace(
            ShipyardDr_LastRun=None,
            Shipyard_LastRun=None,
        )
        self.confirm_calls = []
        self.pay_calls = []
        self.bp_count_reads = 0
        self.ensure_index_calls = 0

    def _shipyard_buy_calc(self, start, count):
        return start, count

    def _shipyard_pay_calc(self, start, count):
        self.pay_calls.append((start, count))
        return start, count

    def _shipyard_buy_enter(self):
        return True

    def _shipyard_cannot_strengthen(self):
        return False

    def _shipyard_ensure_index(self, count):
        # The UI did not select any blueprint, so all requested BPs remain.
        self.ensure_index_calls += 1
        return count if self.ensure_index_calls == 1 else None

    def _shipyard_buy_confirm(self, mode):
        self.confirm_calls.append(mode)

    def _shipyard_get_bp_count(self, index):
        self.bp_count_reads += 1
        return 10 if self.bp_count_reads == 1 else 0


class ShipyardZeroSelectionTest(unittest.TestCase):
    def test_buy_does_not_confirm_when_nothing_was_selected(self):
        shipyard = ZeroSelectionHarness()

        shipyard._shipyard_buy(15)

        self.assertEqual(shipyard.confirm_calls, [])
        self.assertEqual(shipyard.pay_calls, [])
        self.assertIsNone(shipyard.config.ShipyardDr_LastRun)

    def test_use_does_not_confirm_when_nothing_was_selected(self):
        shipyard = ZeroSelectionHarness()

        shipyard._shipyard_use(index=0)

        self.assertEqual(shipyard.confirm_calls, [])
        self.assertEqual(shipyard.bp_count_reads, 1)


if __name__ == '__main__':
    unittest.main()
