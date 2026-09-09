import importlib

from campaign.campaign_hard.campaign_hard import Campaign
from module.campaign.run import CampaignRun
from module.handler.fast_forward import to_map_file_name
from module.hard.assets import *
from module.logger import logger
from module.ocr.ocr import Digit
from module.hard.selection import select_hard_stage

OCR_HARD_REMAIN = Digit(OCR_HARD_REMAIN, letter=(123, 227, 66), threshold=128, alphabet='0123')


class CampaignHard(CampaignRun):
    equipment_has_take_on = False
    campaign: Campaign

    def run(self):
        logger.hr('Campaign hard', level=1)
        selected_stage = self.config.Hard_HardStage
        if getattr(self.config, 'Hard_BalanceBlueprints', False):
            from module.storage.training_inventory import TrainingInventory

            counts = TrainingInventory(self.config, self.device).read_counts(
                ['destroyer', 'cruiser', 'battleship', 'carrier'])
            selected_stage = select_hard_stage(selected_stage, counts)
            logger.info(f'Hard blueprint balance selected {selected_stage}: {counts}')
        name = to_map_file_name(selected_stage)
        self.config.override(
            Campaign_Mode='hard',
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder='fleet1_all_fleet2_standby' if self.config.Hard_HardFleet == 1 else 'fleet1_standby_fleet2_all',
            Emotion_Mode='nothing',  # Dont calculate and dont ignore
        )
        # Equipment take on
        # campaign/campaign_hard/campaign_hard.py Campaign.fleet_preparation()

        # Initial
        self.load_campaign(name='campaign_hard', folder='campaign_hard')  # Load campaign file
        module = importlib.import_module('.' + name, 'campaign.campaign_main')  # Load map from normal mode.
        self.campaign.MAP = module.MAP

        # UI ensure
        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(
            name=selected_stage,
            mode='hard'
        )

        # Run
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('Remain', remain)
        for n in range(remain):
            self.campaign.run()

        self.campaign.ensure_auto_search_exit()
        # self.campaign.equipment_take_off_when_finished()

        # Scheduler
        self.config.task_delay(server_update=True)
        self.config.task_call('Reward')
