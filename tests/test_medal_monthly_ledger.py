import json
import os
import tempfile
import unittest

from module.shop.medal_monthly_ledger import MedalMonthlyLedger


class TestMedalMonthlyLedger(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.ledger = MedalMonthlyLedger(self.root, 'alas', '2026-11')

    def tearDown(self):
        self.temp.cleanup()

    def _prepare(self, ledger=None):
        return (ledger or self.ledger).prepare(
            'RetrofitBBT3', 'bb', 2, 100, 1000, family='RetrofitT3')

    def test_prepare_persists_pending_and_rejects_second_prepare(self):
        receipt = self._prepare()
        restarted = MedalMonthlyLedger(self.root, 'alas', '2026-11')
        self.assertEqual(restarted.load()['pending'], receipt)
        with self.assertRaises(ValueError):
            restarted.prepare('BookRedT3', None, 1, 10, 100)

    def test_bad_delta_and_wrong_txid_preserve_pending(self):
        receipt = self._prepare()
        for txid, after in (('wrong', 800), (receipt['txid'], 801)):
            with self.subTest(txid=txid, after=after):
                with self.assertRaises(ValueError):
                    self.ledger.commit(txid, after)
                self.assertEqual(self.ledger.load()['pending'], receipt)

    def test_exact_commit_persists_counts_and_isolated_profile_and_month(self):
        receipt = self._prepare()
        result = self.ledger.commit(receipt['txid'], 800)
        result['counts']['RetrofitT3']['bb'] = 999
        result['history'].clear()
        self.assertEqual(self.ledger.load()['counts']['RetrofitT3'], {'bb': 2})
        self.assertEqual(len(self.ledger.load()['history']), 1)
        self.assertIsNone(self.ledger.load()['pending'])
        self.assertEqual(MedalMonthlyLedger(self.root, 'alas2', '2026-11').load()['counts']['RetrofitT3'], {})
        self.assertEqual(MedalMonthlyLedger(self.root, 'alas', '2026-12').load()['counts']['RetrofitT3'], {})

    def test_ordinary_receipt_does_not_change_selection_counts(self):
        receipt = self.ledger.prepare('BookRedT3', None, 1, 10, 100)
        self.ledger.commit(receipt['txid'], 90)
        self.assertEqual(self.ledger.load()['counts'], {'RetrofitT3': {}, 'PlateT1': {}})

    def test_corrupt_json_raises_instead_of_resetting(self):
        os.makedirs(os.path.dirname(self.ledger.path))
        with open(self.ledger.path, 'w', encoding='utf-8') as stream:
            stream.write('{broken')
        with self.assertRaises(ValueError):
            self.ledger.load()

    def test_malformed_bool_count_unknown_pending_and_ship_are_rejected(self):
        os.makedirs(os.path.dirname(self.ledger.path))
        base = self.ledger.load()
        cases = []
        bad_bool = json.loads(json.dumps(base))
        bad_bool['counts']['RetrofitT3']['bb'] = True
        cases.append(bad_bool)
        bad_unknown = json.loads(json.dumps(base))
        bad_unknown['pending'] = {
            'txid': 'x', 'item_name': 'MysteryT3', 'choice': None,
            'quantity': 1, 'unit_price': 1, 'before': 2, 'family': None,
        }
        cases.append(bad_unknown)
        bad_ship = json.loads(json.dumps(base))
        bad_ship['pending'] = {
            'txid': 'x', 'item_name': 'ShipT4', 'choice': None,
            'quantity': 1, 'unit_price': 1, 'before': 2, 'family': None,
        }
        cases.append(bad_ship)
        for data in cases:
            with self.subTest(data=data):
                with open(self.ledger.path, 'w', encoding='utf-8') as stream:
                    json.dump(data, stream)
                with self.assertRaises(ValueError):
                    self.ledger.load()
        for item in ('MysteryT3', 'ShipT4'):
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    self.ledger.prepare(item, None, 1, 1, 2)


if __name__ == '__main__':
    unittest.main()
