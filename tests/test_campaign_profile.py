import unittest
from datetime import datetime, timedelta

from module.config.campaign_profile import CampaignProfile
from module.config.config import AzurLaneConfig


class CampaignProfileTest(unittest.TestCase):
    def test_daily_mode_masks_event_sorties_but_not_event_shop_or_archives(self):
        profile = CampaignProfile('daily')

        for task in (
                'Event', 'Event2', 'EventA', 'EventB', 'EventC', 'EventD',
                'EventSp', 'Raid', 'RaidDaily', 'Hospital', 'Coalition',
                'CoalitionSp'):
            with self.subTest(task=task):
                self.assertFalse(profile.allows(task))

        for task in ('Main', 'Main2', 'Main3', 'EventShop', 'WarArchives', 'Reward'):
            with self.subTest(task=task):
                self.assertTrue(profile.allows(task))

    def test_event_mode_masks_main_sorties_and_allows_event_sorties(self):
        profile = CampaignProfile('event')

        for task in ('Main', 'Main2', 'Main3'):
            with self.subTest(task=task):
                self.assertFalse(profile.allows(task))
        for task in ('Event', 'Event2', 'EventA', 'EventD', 'Raid', 'CoalitionSp'):
            with self.subTest(task=task):
                self.assertTrue(profile.allows(task))

    def test_unknown_mode_fails_safe_as_daily_mode(self):
        profile = CampaignProfile('unexpected-value')

        self.assertEqual(profile.mode, 'daily')
        self.assertFalse(profile.allows('Event'))
        self.assertTrue(profile.allows('Main'))

    def test_daily_mode_routes_gems_farming_to_main_2_4_without_mutation(self):
        configured = ('D3', 'event_20260813_cn', 'normal')

        route = CampaignProfile('daily').gems_farming_route(*configured)

        self.assertEqual(route, ('2-4', 'campaign_main', 'normal'))
        self.assertEqual(configured, ('D3', 'event_20260813_cn', 'normal'))

    def test_daily_mode_preserves_an_existing_main_gems_farming_route(self):
        configured = ('3-4', 'campaign_main', 'normal')

        route = CampaignProfile('daily').gems_farming_route(*configured)

        self.assertEqual(route, configured)

    def test_event_mode_preserves_configured_gems_farming_route(self):
        configured = ('D3', 'event_20260813_cn', 'normal')

        route = CampaignProfile('event').gems_farming_route(*configured)

        self.assertEqual(route, configured)

    def test_config_reports_effective_enable_state_without_rewriting_raw_value(self):
        config = object.__new__(AzurLaneConfig)
        config.data = {
            'General': {'CampaignProfile': {'Mode': 'daily'}},
            'Event': {'Scheduler': {'Enable': True}},
        }

        self.assertFalse(config.is_task_enabled('Event'))
        self.assertTrue(config.data['Event']['Scheduler']['Enable'])

    def test_scheduler_excludes_profile_masked_tasks(self):
        due = datetime.now() - timedelta(minutes=1)
        config = object.__new__(AzurLaneConfig)
        config.data = {
            'General': {'CampaignProfile': {'Mode': 'daily'}},
            'Event': {'Scheduler': {
                'Enable': True, 'Command': 'Event', 'NextRun': due}},
            'Main': {'Scheduler': {
                'Enable': True, 'Command': 'Main', 'NextRun': due}},
        }
        config.pending_task = []
        config.waiting_task = []

        previous = AzurLaneConfig.is_hoarding_task
        AzurLaneConfig.is_hoarding_task = False
        try:
            config.get_next_task()
        finally:
            AzurLaneConfig.is_hoarding_task = previous

        self.assertEqual([task.command for task in config.pending_task], ['Main'])


if __name__ == '__main__':
    unittest.main()
