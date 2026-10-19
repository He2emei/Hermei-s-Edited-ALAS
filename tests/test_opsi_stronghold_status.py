import json
import os
import tempfile
import unittest
from unittest.mock import patch

from module.os import stronghold_status
from module.os.tasks.stronghold import OpsiStronghold


class Zone(object):
    zone_id = 42
    cn = '测试海域'


class Config(object):
    config_name = 'alas'


class StrongholdStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_dir = stronghold_status.STATUS_DIR
        stronghold_status.STATUS_DIR = self.temp.name

    def tearDown(self):
        stronghold_status.STATUS_DIR = self.old_dir
        self.temp.cleanup()

    def read(self, profile='alas'):
        with open(os.path.join(self.temp.name, profile + '.json'), encoding='utf-8') as stream:
            return json.load(stream)

    def runner(self, result=None, error=None, found=True):
        obj = OpsiStronghold.__new__(OpsiStronghold)
        obj.config = Config()
        obj.cl1_ap_preserve = lambda: None
        obj.os_map_goto_globe = lambda: None
        obj.globe_update = lambda: None
        obj.find_siren_stronghold = lambda: Zone() if found else None
        obj.os_globe_goto_map = lambda: None
        obj.globe_enter = lambda zone: None
        obj.zone_init = lambda: None
        obj.os_order_execute = lambda **kwargs: None
        obj.fleet_repair = lambda **kwargs: None
        obj.handle_fleet_resolve = lambda **kwargs: None
        def run():
            if error:
                raise error
            return result
        obj.run_stronghold = run
        return obj

    def test_real_try_clear_records_boolean_none_and_exception_without_changing_contract(self):
        for result, status, expected in ((False, 'failed', True), (True, 'cleared', True), (None, 'unknown', True)):
            obj = self.runner(result=result)
            self.assertEqual(obj.try_clear_stronghold(), expected)
            self.assertEqual(self.read()['attempt']['status'], status)
        obj = self.runner(error=RuntimeError('original'))
        with self.assertRaisesRegex(RuntimeError, 'original'):
            obj.try_clear_stronghold()
        self.assertEqual(self.read()['attempt']['status'], 'interrupted')
        obj = self.runner(result=True)
        obj.globe_enter = lambda zone: (_ for _ in ()).throw(RuntimeError('entry failed'))
        with self.assertRaisesRegex(RuntimeError, 'entry failed'):
            obj.try_clear_stronghold()
        self.assertEqual(self.read()['attempt']['status'], 'interrupted')

    def test_percentage_is_native_and_zero_is_the_only_clear_evidence(self):
        attempt = stronghold_status.begin('alas', Zone())
        fleet = type('Fleet', (), {'fleet_index': 2})()
        stronghold_status.fleet_progress('alas', attempt, fleet, '0')
        stronghold_status.finish('alas', attempt, 'cleared')
        self.assertEqual(self.read()['attempt']['remaining_percentage'], '0')
        self.assertEqual(self.read()['attempt']['progress_basis'], 'native_stronghold_percentage_ocr')
        attempt = stronghold_status.begin('alas', Zone())
        stronghold_status.fleet_progress('alas', attempt, fleet, '35')
        stronghold_status.finish('alas', attempt, 'failed')
        self.assertEqual(self.read()['attempt']['remaining_percentage'], '35')
        self.assertEqual(self.read()['attempt']['fleets'], ['2'])

    def test_new_month_attempt_is_separate_from_prior_success(self):
        with patch.object(stronghold_status, '_utc_now', return_value='2026-09-30T15:59:00Z'):
            old = stronghold_status.begin('alas', Zone())
            stronghold_status.finish('alas', old, 'cleared')
        with patch.object(stronghold_status, '_utc_now', return_value='2026-09-30T16:00:00Z'):
            current = stronghold_status.begin('alas', Zone())
        data = self.read()
        self.assertEqual(data['history'][0]['status'], 'cleared')
        self.assertEqual(data['history'][0]['game_month'], '2026-09')
        self.assertEqual(data['attempt']['status'], 'running')
        self.assertEqual(data['attempt']['game_month'], '2026-10')

    def test_missing_check_preserves_attempt_and_profiles_are_isolated(self):
        attempt = stronghold_status.begin('alas', Zone())
        stronghold_status.finish('alas', attempt, 'cleared')
        stronghold_status.check('alas', found=False)
        self.assertEqual(self.read('alas')['attempt']['status'], 'cleared')
        self.assertFalse(self.read('alas')['last_check']['stronghold_found'])
        other = stronghold_status.begin('alas2', Zone())
        stronghold_status.finish('alas2', other, 'failed')
        self.assertEqual(self.read('alas2')['profile'], 'alas2')
        self.assertEqual(self.read('alas')['attempt']['status'], 'cleared')

    def test_malformed_history_recovers_without_failing_recording(self):
        with open(os.path.join(self.temp.name, 'alas.json'), 'w', encoding='utf-8') as stream:
            stream.write('{bad json')
        attempt = stronghold_status.begin('alas', Zone())
        stronghold_status.finish('alas', attempt, 'failed')
        data = self.read()
        self.assertEqual(data['history'][0]['status'], 'failed')
        self.assertEqual(data['attempt']['attempt_id'], attempt['attempt_id'])

    def test_atomic_write_failure_does_not_change_try_clear_result(self):
        obj = self.runner(result=False)
        with patch.object(stronghold_status, '_write', return_value=False):
            self.assertTrue(obj.try_clear_stronghold())

    def test_running_attempt_is_recorded_before_attempt_finishes(self):
        stronghold_status.begin('alas', Zone())
        data = self.read()
        self.assertEqual(data['schema_version'], stronghold_status.SCHEMA_VERSION)
        self.assertEqual(data['attempt']['status'], 'running')
        self.assertIsNone(data['attempt']['progress_basis'])


    def test_same_second_attempts_update_history_by_uuid_and_cap_at_50(self):
        with patch.object(stronghold_status, '_utc_now', return_value='2026-10-20T00:00:00Z'):
            attempts = [stronghold_status.begin('alas', Zone()) for _ in range(2)]
        self.assertNotEqual(attempts[0]['attempt_id'], attempts[1]['attempt_id'])
        stronghold_status.finish('alas', attempts[0], 'cleared')
        stronghold_status.finish('alas', attempts[1], 'failed')
        self.assertEqual([x['status'] for x in self.read()['history']], ['cleared', 'failed'])
        for _ in range(55):
            stronghold_status.finish('alas', stronghold_status.begin('alas', Zone()), 'unknown')
        self.assertEqual(len(self.read()['history']), 50)

    def test_replace_failure_keeps_previous_json_valid_and_does_not_propagate(self):
        old = stronghold_status.begin('alas', Zone())
        stronghold_status.finish('alas', old, 'cleared')
        with open(os.path.join(self.temp.name, 'alas.json'), 'rb') as stream:
            before = stream.read()
        obj = self.runner(result=False)
        with patch('module.os.stronghold_status.os.replace', side_effect=OSError('replace failed')):
            self.assertTrue(obj.try_clear_stronghold())
        with open(os.path.join(self.temp.name, 'alas.json'), 'rb') as stream:
            after = stream.read()
        self.assertEqual(after, before)
        self.assertEqual(json.loads(after)['attempt']['status'], 'cleared')

    def test_run_one_fleet_uses_native_zero_and_nonzero_repair_branches(self):
        def make(percentage, need_repair):
            obj = OpsiStronghold.__new__(OpsiStronghold)
            obj.config = type('Cfg', (), {'override': lambda self, **kwargs: None, 'config_name': 'alas'})()
            obj.need_repair = need_repair
            obj.zone = Zone()
            obj._stronghold_status_attempt = stronghold_status.begin('alas', Zone())
            obj.fleet_set = lambda index: None
            obj.run_auto_search = lambda **kwargs: None
            obj.hp_reset = lambda: None
            obj.hp_get = lambda: None
            obj.get_stronghold_percentage = lambda: percentage
            obj.globe_goto = lambda *args, **kwargs: None
            obj.zone_nearest_azur_port = lambda zone: zone
            obj.handle_fog_block = lambda **kwargs: None
            return obj
        fleet = type('Fleet', (), {'fleet_index': 2})()
        self.assertIs(make('0', []).run_stronghold_one_fleet(fleet), True)
        self.assertIs(make('17', [True]).run_stronghold_one_fleet(fleet), False)


if __name__ == '__main__':
    unittest.main()
