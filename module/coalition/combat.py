from module.base.timer import Timer
from module.campaign.campaign_base import CampaignBase
from module.coalition.assets import *
from module.coalition.ui import CoalitionUI
from module.combat.assets import BATTLE_PREPARATION
from module.coalition.truth_academy import (
    TRUTH_BATTLE_RESULT_CONFIRM,
    TRUTH_TOTAL_REWARDS_LEAVE,
    TruthAcademyReader,
)
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.logger import logger
from module.os_ash.assets import BATTLE_STATUS
from module.coalition.truth_academy_emotion import TruthAcademyEmotionReader


class CoalitionCombat(CoalitionUI, CampaignBase):
    battle_status_click_interval = 2

    def handle_battle_preparation(self):
        """Safely stop the verified CN single-fleet low-mood dead end."""
        if (self.config.SERVER == 'cn' and
                self.config.Campaign_Event == 'coalition_20261124' and
                self.config.Coalition_Fleet == 'single' and
                self.appear(BATTLE_PREPARATION, offset=(20, 20))):
            reader = getattr(self, '_truth_academy_emotion_reader', None)
            if reader is None:
                reader = TruthAcademyEmotionReader()
                self._truth_academy_emotion_reader = reader
            if reader.read_low_mood_toast(self.device.image):
                self.device.screenshot()
                if (self.appear(BATTLE_PREPARATION, offset=(20, 20)) and
                        reader.read_low_mood_toast(self.device.image)):
                    logger.warning(
                        'Truth Academy single-fleet low-mood lockout confirmed; '
                        'returning to event main and deferring 120 minutes')
                    self.coalition_map_exit('coalition_20261124')
                    self.config.task_delay(minute=120)
                    raise ScriptEnd('Truth Academy low emotion; deferred 120 minutes')
                # A possible toast changed across frames. Consume this check and
                # never issue the underlying battle-preparation click on it.
                return True

        return super().handle_battle_preparation()

    def handle_truth_academy_reward(self):
        """Safely dismiss only the two verified CN Truth Academy settlements."""
        if (self.config.SERVER != 'cn' or
                self.config.Campaign_Event != 'coalition_20261124'):
            return False

        reader = TruthAcademyReader()
        reward = reader.read_reward(self.device.image)
        if reward not in ('battle_result', 'total_rewards'):
            return False

        # A second independent screenshot is required before any event-specific click.
        self.device.screenshot()
        if reader.read_reward(self.device.image) != reward:
            # Consume this changed frame so legacy reward clicks cannot act on it.
            return True

        if reward == 'battle_result':
            button = TRUTH_BATTLE_RESULT_CONFIRM
        else:
            button = TRUTH_TOTAL_REWARDS_LEAVE
        self.appear_then_click(button, offset=(0, 0), interval=2)
        return True

    def auto_search_combat_early_end(self):
        """Yield settlement screens to the double-frame handler without clicking."""
        if (self.config.SERVER != 'cn' or
                self.config.Campaign_Event != 'coalition_20261124'):
            return False
        return TruthAcademyReader().read_reward(self.device.image) in (
            'battle_result', 'total_rewards')

    def coalition_combat_re_enter(self, skip_first_screenshot=True):
        """
        Pages:
            in: battle_status
            out: is_combat_executing
        """
        logger.info('Coalition combat re-enter')
        status_clicked = False
        click_timer = Timer(0.3)
        click_last = Timer(1, count=3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Settlement screens can retain battle HUD cues. Classify them before
            # loading/HUD checks so they reach the event's double-frame gate.
            if self.handle_truth_academy_reward():
                continue

            # End
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                break
            if self.in_coalition():
                raise CampaignEnd

            if self.appear_then_click(BATTLE_STATUS, offset=(80, 20), interval=2):
                # About (+53, +3)
                continue
            if self.appear_then_click(COALITION_REWARD_CONFIRM, offset=(20, 20), interval=2):
                # Stop clicking BATTLE_STATUS because combat ends
                status_clicked = False
                continue
            # Coalition 20251120 has ship drop
            if self.handle_get_ship():
                continue
            if self.handle_battle_status():
                status_clicked = True
                click_last.reset()
                continue
            # Keep clicking BATTLE_STATUS to skip animations
            if status_clicked:
                if click_timer.reached() and not click_last.reached():
                    self.device.click(BATTLE_STATUS)
                    click_timer.reset()

    def auto_search_combat_end(self):
        if self.appear(BATTLE_STATUS, offset=(80, 20)):
            return True
        return False

    def coalition_combat(self):
        """
        Pages:
            in: is_coalition
            out: is_coalition
        """
        self.battle_count = 0
        self.combat_preparation(emotion_reduce=False)

        try:
            while 1:
                logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
                self.auto_search_combat_execute(
                    emotion_reduce=self.battle_count == 0 or self.config.Coalition_Fleet == 'single',
                    fleet_index=1
                )
                self.coalition_combat_re_enter()
                self.battle_count += 1
        except CampaignEnd:
            logger.info('Coalition combat end.')
