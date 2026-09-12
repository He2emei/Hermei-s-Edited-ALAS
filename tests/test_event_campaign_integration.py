import copy
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.run import CampaignRun
from module.event.fleet_preparation import EventFleetPreparation


class FakeMergedConfig:
    def __init__(self, base):
        self.__dict__.update(base.__dict__)
        self.overrides = []

    def merge(self, _map_config):
        return self

    def override(self, **values):
        self.overrides.append(values)
        self.__dict__.update(values)


class EventCampaignIntegrationTest(unittest.TestCase):
    def _runner(self, stage, *, source_index=5):
        class BaseConfig(SimpleNamespace):
            def __deepcopy__(self, _memo):
                return FakeMergedConfig(self)

        config = BaseConfig(EventFleet_AutoPrepare=True,
                            Scheduler_Command='Event',
                            Campaign_Event='event_test',
                            Campaign_Name=stage,
                            cross_get=Mock(return_value=source_index))
        runner = object.__new__(CampaignRun)
        runner.config = config
        runner.device = object()
        return runner

    @staticmethod
    def _fake_campaign_module():
        created = []

        class FakeCampaign:
            def __init__(self, config, device):
                self.config = config
                self.device = device
                created.append(self)

        return types.SimpleNamespace(Config=lambda: object(), Campaign=FakeCampaign), created

    @patch('module.event.fleet_source.EventFleetSource')
    @patch('module.campaign.run.importlib.import_module')
    def test_c_load_reads_account_fleet2_and_forces_fleet1_standby_fleet2_all(
            self, import_module, source_class):
        module, created = self._fake_campaign_module()
        import_module.return_value = module
        source = source_class.return_value
        source.read.return_value = [{'name': '苏维埃同盟', 'level': 125, 'side': 'main'}]
        runner = self._runner('C1', source_index=5)

        runner.load_campaign('c1', folder='event_test')

        runner.config.cross_get.assert_called_once_with('Event.Fleet.Fleet2', default=0)
        source_class.assert_called_once_with(runner.config, runner.device)
        source.read.assert_called_once_with(5)
        self.assertEqual(created[0].config.overrides, [{
            'Fleet_FleetOrder': 'fleet1_standby_fleet2_all',
            'Fleet_Fleet1': 1,
            'Fleet_Fleet2': 2,
        }])

    @patch('module.event.fleet_source.EventFleetSource')
    @patch('module.campaign.run.importlib.import_module')
    def test_d_and_sp_force_mob_boss_without_reading_source(self, import_module, source_class):
        module, created = self._fake_campaign_module()
        import_module.return_value = module

        for stage in ('D1', 'SP'):
            with self.subTest(stage=stage):
                runner = self._runner(stage)
                runner.load_campaign(stage.lower(), folder='event_test')
                self.assertEqual(created[-1].config.overrides[-1], {
                    'Fleet_FleetOrder': 'fleet1_mob_fleet2_boss',
                    'Fleet_Fleet1': 1,
                    'Fleet_Fleet2': 2,
                })

        source_class.assert_not_called()

    def test_c_auxiliary_fill_uses_unrestricted_slot_and_reads_physical_slot_four(self):
        prep = object.__new__(EventFleetPreparation)
        chosen = {'name': '唐斯', 'level': 125}
        prep.device = SimpleNamespace(click=Mock(), sleep=Mock())
        prep._at_preparation = Mock(return_value=True)
        prep._wait = Mock()
        prep._find_ship = Mock(return_value=(object(), chosen))
        prep._read_slot = Mock(return_value=chosen)

        result = prep._fill_slot(5, auxiliary=True, read_index=3)

        self.assertEqual(result, chosen)
        prep._find_ship.assert_called_once_with(None, auxiliary=True, excluded=())
        prep._read_slot.assert_called_once_with(3)
        self.assertEqual(prep.device.click.call_count, 3)


if __name__ == '__main__':
    unittest.main()
