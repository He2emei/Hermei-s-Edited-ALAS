from module.base.timer import Timer
from module.combat.assets import *
from module.combat.battle_result import handle_battle_result_screen
from module.exception import CampaignEnd
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.logger import logger
from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler.assets import *
from module.os_handler.enemy_searching import EnemySearchingHandler
from module.statistics.azurstats import DropImage
from module.ui.assets import BACK_ARROW
from module.ui.switch import Switch


class FleetLockSwitch(Switch):
    def handle_additional(self, main):
        # A game bug that AUTO_SEARCH_REWARD from the last cleared zone popups
        if main.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        return False


fleet_lock = FleetLockSwitch('Fleet_Lock', offset=(10, 120))
fleet_lock.add_state('on', check_button=OS_FLEET_LOCKED)
fleet_lock.add_state('off', check_button=OS_FLEET_UNLOCKED)


class MapEventHandler(EnemySearchingHandler):
    ash_popup_canceled = False

    def handle_map_get_items(self, interval=2, drop=None):
        if self.is_in_map():
            return False

        if self.appear(GET_ITEMS_1, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_1} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_2, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_2} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_3, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_3} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ADAPTABILITY, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ADAPTABILITY} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_MEOWFFICER_ITEMS_1, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_MEOWFFICER_ITEMS_1} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_MEOWFFICER_ITEMS_2, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_MEOWFFICER_ITEMS_2} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True

        return False

    def handle_map_archives(self, drop=None):
        if self.appear(MAP_ARCHIVES, interval=5):
            if drop:
                drop.add(self.device.image)
            logger.info(f'{MAP_ARCHIVES} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear_then_click(MAP_WORLD, offset=(20, 20), interval=5):
            return True

        return False

    def handle_os_game_tips(self):
        # Close game tips the first time enabling auto search
        if self.appear_then_click(OS_GAME_TIPS, offset=(20, 20), interval=3):
            return True

        return False

    def handle_os_mission_page(self):
        """
        Close the operation info page (作战情报, the mission overview) that covers the map.

        The map's `情报` button (the same button IN_MAP points at) opens this page, and the 2026-08
        CN operation overview can also open it after a globe click (see os_globe_goto_map). The page
        is not a page ui_get_current_page() knows, and it is not the map either: its background is
        blurred, so is_in_map() fails while it is on the display. Every operation siren loop that
        waits for the map therefore polls the map event buttons until the sixty second stuck check
        of the device ends the task with `GameStuckError: Wait too long`: live 2026-08-29 (36 dumps
        trapped in storage_enter()) and live 2026-09-21 23:06:47 OpsiMeowfficerFarming (dump
        log/error/1790003207571), where the auto search loop of zone 144 polled for sixty seconds
        after a stray click on that button opened the page.

        MISSION_QUIT is the close button of the page, the same exit os_mission_quit() clicks, so no
        new template or screen layout is assumed here. A page that is still there is clicked again
        after the interval, which is what the other loops of this handler do as well.

        Returns:
            bool: If clicked.
        """
        if self.appear_then_click(MISSION_QUIT, offset=(20, 20), interval=2):
            return True

        return False

    def handle_ash_popup(self):
        name = 'ASH'
        # 2021.12.09
        # Ash popup no longer shows red letters, so change it to letter `Ashes Coordinates`
        if self.appear(POPUP_CONFIRM, offset=self._popup_offset) \
                and self.appear(POPUP_CANCEL, offset=self._popup_offset, interval=2) \
                and self.appear(ASH_POPUP_CHECK, offset=(20, 20)):
            POPUP_CANCEL.name = POPUP_CANCEL.name + '_' + name
            self.device.click(POPUP_CANCEL)
            POPUP_CANCEL.name = POPUP_CANCEL.name[:-len(name) - 1]
            self.ash_popup_canceled = True
            return True
        else:
            return False

    def handle_map_event(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            str: Event that handled
        """
        # The operation info page is a definite state (its close button is a template match), and
        # nothing else can be handled while it covers the map, so it is closed first.
        if self.handle_os_mission_page():
            return 'os_mission_page'
        # A battle result screen is not a map event and it is not a page either, but every
        # operation siren loop that waits for is_in_map() ends in GameStuckError while it stays
        # on the display: auto search can be stopped while a battle is still running, and the
        # result screen of that battle appears afterwards, when no combat loop is watching.
        if handle_battle_result_screen(self):
            return 'battle_result'
        if self.handle_map_get_items(drop=drop):
            return 'map_get_items'
        if self.handle_os_game_tips():
            return 'os_game_tips'
        if self.handle_map_archives(drop=drop):
            return 'map_archives'
        if self.handle_guild_popup_cancel():
            return 'guild_popup_cancel'
        if self.handle_ash_popup():
            return 'ash_popup'
        if self.handle_urgent_commission(drop=drop):
            return 'urgent_commission'
        if self.handle_story_skip():
            return 'story_skip'

        return ''

    _os_in_map_confirm_timer = Timer(1.5, count=3)

    def handle_os_in_map(self):
        """
        Returns:
            bool: If is in map and confirmed.
        """
        if self.is_in_map():
            if self._os_in_map_confirm_timer.reached():
                return True
            else:
                return False
        else:
            self._os_in_map_confirm_timer.reset()
            return False

    def ensure_no_map_event(self):
        self._os_in_map_confirm_timer.reset()

        for _ in self.loop():
            if self.handle_map_event():
                continue
            # End
            if self.handle_os_in_map():
                break

    def os_auto_search_quit(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            bool: True if current map cleared
        """
        confirm_timer = Timer(1.2, count=3).start()
        cleared = False
        for _ in self.loop():
            if self.appear(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
                # An info bar on this screen is the game saying it has no auto searchable event
                # left, which is the end of the zone, so it is only looked at, never waited for.
                # The bar of the archived frame below stays on the display while this reward panel
                # is open and goes away once the panel is dismissed: waiting for the bar before
                # the click waits for the click itself, and the sixty second stuck check of the
                # device ends the task with `GameStuckError: Wait too long` (live 2026-09-22
                # 14:16:13, dump log/error/1790057773446, where wait_until_info_bar_disappear()
                # polled the same picture until the check fired). Clicking the panel with an info
                # bar up is what the other AUTO_SEARCH_REWARD call sites do, and the click target
                # (575, 598, 721, 646) is below the bar area (200, 173, 1080, 348).
                if self.info_bar_count():
                    cleared = True
                if drop:
                    drop.handle_add(main=self, before=4)
                self.device.click(AUTO_SEARCH_REWARD)
                self.interval_reset([
                    AUTO_SEARCH_REWARD,
                    AUTO_SEARCH_OS_MAP_OPTION_ON,
                    AUTO_SEARCH_OS_MAP_OPTION_OFF,
                    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                ])
                confirm_timer.reset()
                continue
            if self.handle_map_event():
                confirm_timer.reset()
                continue
            if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=2):
                # Sometimes entered globe map after clicking AUTO_SEARCH_REWARD
                # because of duplicated clicks and clicks to places outside the map
                confirm_timer.reset()
                continue
            # Donno why but it just entered storage, exit it anyway
            # Equivalent to is_in_storage, but can't inherit StorageHandler here
            # STORAGE_CHECK is a duplicate name, this is the os_handler/STORAGE_CHECK, not handler/STORAGE_CHECK
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=5):
                logger.info(f'{STORAGE_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                confirm_timer.reset()
                continue

            # End
            if self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        return cleared

    def handle_os_auto_search_map_option(self, drop=None, enable=True):
        """
        Args:
            drop (DropImage):
            enable (bool): True/False, or None for doing nothing.

        Returns:
            bool: If clicked.
        """
        if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120)):
            if self.info_bar_count() >= 2:
                self.device.screenshot_interval_set()
                self.os_auto_search_quit(drop=drop)
                raise CampaignEnd
        if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120)):
            if self.info_bar_count() >= 2:
                self.device.screenshot_interval_set()
                self.os_auto_search_quit(drop=drop)
                raise CampaignEnd
        if self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)):
            self.device.screenshot_interval_set()
            if self.os_auto_search_quit(drop=drop):
                # No more items on current map
                raise CampaignEnd
            else:
                # Auto search stopped but map hasn't been cleared
                return True

        if enable is None:
            pass
        elif enable:
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120), interval=3):
                self.device.click(AUTO_SEARCH_OS_MAP_OPTION_OFF)
                self.interval_reset(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED)
                return True
            # Game client bugged sometimes, AUTO_SEARCH_OS_MAP_OPTION_OFF grayed out but still functional
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120), interval=3):
                self.device.click(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED)
                self.interval_reset(AUTO_SEARCH_OS_MAP_OPTION_OFF)
                return True
        else:
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120), interval=3):
                self.device.click(AUTO_SEARCH_OS_MAP_OPTION_ON)
                return True

        return False

    def handle_os_map_fleet_lock(self, enable=None):
        """
        Args:
            enable (bool): Default to None, use Campaign_UseFleetLock.

        Returns:
            bool: If switched.
        """
        # Fleet lock depends on if it appear on map, not depends on map status.
        # Because if already in map, there's no map status,
        if not fleet_lock.appear(main=self):
            logger.info('No fleet lock option.')
            return False

        if enable is None:
            enable = self.config.Campaign_UseFleetLock
        state = 'on' if enable else 'off'
        changed = fleet_lock.set(state, main=self)

        return changed
