"""Read-only integration checks for the two production config migrations."""

import copy
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from module.campaign.campaign_event import CampaignEvent
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get


EVENT = 'coalition_20261124'
LEGACY_EVENT = 'coalition_20260723'
PROFILES = ('alas', 'alas2')


def workspace_root():
    for candidate in (Path.cwd(),) + tuple(Path.cwd().parents):
        if ((candidate / 'AzurLaneAutoScript-Original').is_dir() and
                (candidate / 'AzurLaneAutoScript-Use').is_dir()):
            return candidate
    raise unittest.SkipTest('Private production migration check requires local sibling checkouts')


def field_paths(value, prefix=''):
    """Return JSON field paths, ignoring value changes from normal migration."""
    if isinstance(value, dict):
        if not value:
            return {prefix}
        paths = set()
        for key, child in value.items():
            path = '{}.{}'.format(prefix, key) if prefix else key
            paths.update(field_paths(child, path))
        return paths
    if isinstance(value, list):
        # Preserve the containing field and list cardinality without embedding values.
        return {prefix + '[{}]'.format(len(value))}
    return {prefix}


class TruthAcademyConfigIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_dir = workspace_root() / 'AzurLaneAutoScript-Use' / 'config'
        cls.updater = ConfigUpdater()

    def read_production(self, profile):
        path = self.config_dir / '{}.json'.format(profile)
        raw = path.read_bytes()
        data = json.loads(raw.decode('utf-8'))
        return path, raw, data

    def test_both_production_configs_keep_all_json_fields_in_memory_migration(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                path, raw, original = self.read_production(profile)
                before_hash = hashlib.sha256(raw).hexdigest()
                supplied = copy.deepcopy(original)
                migrated = self.updater.config_update(supplied)

                self.assertEqual(supplied, original, 'config_update mutated its input')
                self.assertEqual(field_paths(original), field_paths(migrated),
                                 'full JSON field paths/cardinality changed')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_hash,
                                 'production JSON changed during read-only validation')

                # The production package is CN; both task selectors must accept the migrated value.
                for task in ('Coalition', 'CoalitionSp'):
                    options = self.updater.args[task]['Campaign']['Event']['option_cn']
                    selected = deep_get(migrated, '{}.Campaign.Event'.format(task))
                    self.assertIn(EVENT, options)
                    self.assertIn(selected, options)

    def test_options_follow_native_current_event_per_locale(self):
        args = self.updater.args
        for task in ('Coalition', 'CoalitionSp'):
            for server in ('en', 'jp', 'tw'):
                with self.subTest(task=task, server=server):
                    options = args[task]['Campaign']['Event']['option_' + server]
                    expected = LEGACY_EVENT if server == 'tw' else EVENT
                    self.assertIn(expected, options)

                    # Native schema owns current locale options; migrations stay valid.
                    _, _, current = self.read_production('alas')
                    foreign = copy.deepcopy(current)
                    package = {
                        'en': 'com.YoStarEN.AzurLane',
                        'jp': 'com.YoStarJP.AzurLane',
                        'tw': 'com.hkmanjuu.azurlane.gp',
                    }[server]
                    foreign['Alas']['Emulator']['PackageName'] = package
                    foreign[task]['Campaign']['Event'] = EVENT
                    migrated = self.updater.config_update(foreign)
                    selected = deep_get(migrated, '{}.Campaign.Event'.format(task))
                    self.assertIn(selected, options)
                    self.assertEqual(selected, expected)

    def test_zero_pt_limit_does_not_call_coalition_ocr(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                _, _, production = self.read_production(profile)
                migrated = self.updater.config_update(copy.deepcopy(production))
                limit = deep_get(migrated, 'EventGeneral.EventGeneral.PtLimit')
                self.assertEqual(limit, 0)

                config = SimpleNamespace(
                    SERVER='cn', Campaign_Event=EVENT, EventGeneral_PtLimit=limit,
                    Scheduler_Command='Coalition', Campaign_Name='easy',
                )
                app = SimpleNamespace(config=config, get_event_pt=Mock(
                    side_effect=AssertionError('PT OCR must not be called at PtLimit=0')))
                self.assertFalse(CampaignEvent.event_pt_limit_triggered(app))
                app.get_event_pt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
