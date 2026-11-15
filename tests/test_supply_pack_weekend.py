import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.freebies.supply_pack import SupplyPack


class SupplyPackWeekendFallbackTest(unittest.TestCase):
    def run_pack(self, *, server='cn', weekday=6, target=0, oil=21000):
        pack = SupplyPack.__new__(SupplyPack)
        pack.config = SimpleNamespace(SERVER=server, SupplyPack_DayOfWeek=target)
        pack.ui_ensure = Mock()
        pack.goto_supply_pack = Mock()
        pack.get_oil = Mock(return_value=oil)
        pack._buy_cn_weekly_free = Mock()
        pack.supply_pack_buy = Mock()
        with patch('module.freebies.supply_pack.get_server_weekday', return_value=weekday):
            pack.run()
        return pack

    def test_cn_weekday_high_oil_skips(self):
        for weekday in range(5):
            with self.subTest(weekday=weekday):
                pack = self.run_pack(weekday=weekday, oil=25000)
                pack._buy_cn_weekly_free.assert_not_called()
                pack.supply_pack_buy.assert_not_called()

    def test_cn_weekend_high_oil_tries_strict_weekly_claim(self):
        for weekday in (5, 6):
            for oil in (21000, 25000):
                with self.subTest(weekday=weekday, oil=oil):
                    pack = self.run_pack(weekday=weekday, oil=oil)
                    pack._buy_cn_weekly_free.assert_called_once_with()
                    pack.supply_pack_buy.assert_not_called()

    def test_cn_low_oil_preserves_target_eligibility(self):
        for weekday in range(7):
            with self.subTest(weekday=weekday):
                pack = self.run_pack(weekday=weekday, target=4, oil=20000)
                if weekday >= 4:
                    pack._buy_cn_weekly_free.assert_called_once_with()
                else:
                    pack._buy_cn_weekly_free.assert_not_called()
                pack.supply_pack_buy.assert_not_called()

    def test_preferred_sunday_target_still_delays_saturday(self):
        pack = self.run_pack(weekday=5, target=6, oil=25000)
        pack._buy_cn_weekly_free.assert_not_called()
        pack.supply_pack_buy.assert_not_called()

    def test_non_cn_high_oil_weekend_still_skips(self):
        for weekday in (5, 6):
            with self.subTest(weekday=weekday):
                pack = self.run_pack(server='en', weekday=weekday, oil=25000)
                pack._buy_cn_weekly_free.assert_not_called()
                pack.supply_pack_buy.assert_not_called()

    def test_non_cn_low_oil_keeps_legacy_purchase_path(self):
        for weekday in range(7):
            with self.subTest(weekday=weekday):
                pack = self.run_pack(server='en', weekday=weekday, target=4, oil=20000)
                if weekday >= 4:
                    pack.supply_pack_buy.assert_called_once()
                else:
                    pack.supply_pack_buy.assert_not_called()
                pack._buy_cn_weekly_free.assert_not_called()


if __name__ == '__main__':
    unittest.main()
