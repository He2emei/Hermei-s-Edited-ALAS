import types
import unittest
from unittest.mock import patch

from module.campaign.gems_farming import GemsFarming
from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignRun


class FakeConfig:
    def __init__(self, use_2x_book):
        self.Campaign_Use2xBook = use_2x_book
        self.GemsFarming_ChangeVanguard = 'none'
        self.overrides = []

    def override(self, **values):
        self.overrides.append(values)
        for key, value in values.items():
            setattr(self, key, value)


class FakeCampaign:
    def __init__(self, device, config):
        self.device = device
        self.config = config


class TestGemsEvent2xBook(unittest.TestCase):
    def _load(self, folder, use_2x_book):
        runner = object.__new__(GemsFarming)
        runner.config = FakeConfig(use_2x_book)
        runner.module = types.SimpleNamespace(Campaign=FakeCampaign)
        runner.campaign = FakeCampaign(object(), runner.config)
        def load_base(_runner, _name, _folder):
            return None

        def init_campaign(campaign, device, config):
            campaign.device = device
            campaign.config = config

        with patch.object(CampaignRun, 'load_campaign', load_base), \
                patch.object(CampaignBase, '__init__', init_campaign):
            runner.load_campaign('a3', folder=folder)
        return runner.campaign.config

    def test_event_campaign_preserves_true_and_false(self):
        self.assertTrue(self._load('event_20261103_cn', True).Campaign_Use2xBook)
        self.assertFalse(self._load('event_20261103_cn', False).Campaign_Use2xBook)

    def test_main_and_unknown_campaigns_force_false(self):
        for folder in ('campaign_main', 'unknown_campaign', None):
            with self.subTest(folder=folder):
                config = self._load(folder, True)
                self.assertFalse(config.Campaign_Use2xBook)
                self.assertIn({'Campaign_Use2xBook': False}, config.overrides)


if __name__ == '__main__':
    unittest.main()
