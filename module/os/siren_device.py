"""
Mixin for ScanningDevice (塞壬探测装置/吊机) Bug exploitation.

核心功能：CL1 运转中遇到 ScanningDevice 时，选择选项2（紫币换黄币），
然后跳转到预配置的高级海域使用 2 次高级 ScanningDevice，再返回 CL1 继续。

参考 wess09 的 SirenBug 实现，遵循 heremei rebase-friendly 原则。
"""
import time

from module.base.timer import Timer
from module.handler.assets import POPUP_CONFIRM
from module.logger import logger


class SirenDeviceHandler:
    """
    [heremei] ScanningDevice Bug exploitation Mixin.
    注入到 OSMap 继承链中，提供卡装置相关方法。
    """

    # 标志位：story_skip 中 OCR 检测到的 ScanningDevice 确认
    is_siren_device_confirmed = False

    # ========== Config Helpers ==========

    @property
    def _is_siren_research_enabled(self):
        """
        Check if siren research feature is enabled in config.

        Returns:
            bool: True if enabled
        """
        return getattr(self.config, 'OpsiSirenBug_SirenResearch_Enable', False)

    def _should_skip_siren_research(self, grid):
        """
        Check if siren research device should be skipped.

        Args:
            grid: The grid containing the device

        Returns:
            bool: True if should skip (feature disabled)
        """
        if hasattr(grid, 'is_scanning_device') and grid.is_scanning_device:
            if not self._is_siren_research_enabled:
                logger.info(f'[heremei] Grid {grid} is ScanningDevice but feature disabled, skip')
                return True
            else:
                logger.info(f'[heremei] Grid {grid} is ScanningDevice, feature enabled, proceed')
        return False

    # ========== Story Option Selection ==========

    def _select_siren_device_option(self, options):
        """
        [heremei] Select appropriate option for story popup.
        Called from story_skip() hook to replace default option selection.

        When ScanningDevice is detected (3 options with OCR keywords),
        selects option 2 (index 1, purple coins → resources).
        Otherwise falls back to default STORY_OPTION.

        Args:
            options: List of detected story option buttons

        Returns:
            Button: The option to click
        """
        options_count = len(options)

        # Only check for ScanningDevice when exactly 3 options present
        if options_count == 3:
            is_siren_device = self._detect_siren_device_by_ocr(options)
            self.is_siren_device_confirmed = is_siren_device

            if is_siren_device:
                if getattr(self.config, '_disable_siren_research', False):
                    logger.info('[heremei] ScanningDevice detected but disabled, select option 3 (leave)')
                    return options[2]
                else:
                    logger.info('[heremei] ScanningDevice detected, select option 2 (purple coins)')
                    return options[1]
        else:
            self.is_siren_device_confirmed = False

        # Fallback to default behavior
        try:
            return options[self.config.STORY_OPTION]
        except IndexError:
            return options[0]

    def _detect_siren_device_by_ocr(self, options):
        """
        Use OCR to detect if current story options are from a ScanningDevice.

        Checks for keywords: '探测', '隐藏', '离开', '取消'
        If 2+ options contain these keywords, confirmed as ScanningDevice.

        Args:
            options: List of 3 option buttons

        Returns:
            bool: True if ScanningDevice confirmed
        """
        try:
            from module.ocr.ocr import Ocr

            keywords = ['探测', '隐藏', '离开', '取消']
            match_count = 0

            for i, option in enumerate(options):
                text = Ocr(option, lang='cnocr').ocr(self.device.image)
                logger.info(f'[heremei] Option {i + 1} OCR: "{text}"')

                if any(k in str(text) for k in keywords):
                    match_count += 1

            logger.info(f'[heremei] ScanningDevice OCR: {match_count}/3 options match keywords')

            if match_count >= 2:
                logger.info('[heremei] Confirmed ScanningDevice (OCR)')
                return True
            else:
                logger.info('[heremei] Not ScanningDevice (OCR)')
                return False

        except Exception as e:
            logger.warning(f'[heremei] ScanningDevice OCR detection failed: {e}')
            return False

    # ========== Precise Option Selection (for Bug exploitation) ==========

    def _select_story_option_by_index(self, target_index, options_count=3):
        """
        Select a specific story option by index.
        Used during Bug exploitation to precisely pick option 2 or 3.

        Args:
            target_index: 0-based index of option to select
            options_count: Expected total number of options

        Returns:
            bool: True if successfully clicked
        """
        option_confirm_timer = Timer(1.5, count=3).start()
        while option_confirm_timer.reached() is False:
            self.device.screenshot()
            options = self._story_option_buttons_2()
            if len(options) == options_count:
                try:
                    select = options[target_index]
                    self.device.click(select)
                    time.sleep(0.5)
                    return True
                except IndexError:
                    select = options[0]
                    self.device.click(select)
                    time.sleep(0.5)
                    return False
            time.sleep(0.3)
        return False

    def _click_story_confirm_button(self):
        """
        Click the POPUP_CONFIRM button after a story option selection.

        Returns:
            bool: True if successfully clicked
        """
        confirm_timer = Timer(3, count=6).start()
        while confirm_timer.reached() is False:
            self.device.screenshot()
            if self.appear(POPUP_CONFIRM, offset=(20, 20), interval=0):
                self.device.click(POPUP_CONFIRM)
                time.sleep(0.5)
                return True
            time.sleep(0.3)
        return False

    # ========== CL1 Hook ==========

    def _on_scanning_device_in_cl1(self, grid, drop=None):
        """
        [heremei] Hook called from map_rescan_current() when ScanningDevice
        is found during CL1 leveling.

        If SirenResearch is disabled: skip (original behavior).
        If enabled: interact with device, then trigger Bug exploitation.

        Args:
            grid: The ScanningDevice grid
            drop: DropRecord

        Returns:
            bool: True
        """
        if not self._is_siren_research_enabled:
            # Original behavior: skip scanning device in CL1
            logger.info('[heremei] SirenResearch disabled, skip ScanningDevice in CL1')
            self._solved_map_event.add('is_scanning_device')
            return True

        # SirenResearch enabled: interact with the device
        logger.hr('[heremei] ScanningDevice found in CL1, processing', level=2)

        # Move to device and trigger story options
        # story_skip (with our hook) will auto-select option 2 (purple coins)
        self.device.click(grid)
        result = self.wait_until_walk_stable(
            drop=drop, walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))

        if getattr(self, 'is_siren_device_confirmed', False):
            # Device interaction succeeded, run auto search to clear exposed enemies
            logger.info('[heremei] ScanningDevice interaction confirmed, clearing exposed enemies')
            self.os_auto_search_run(drop=drop)

        self._solved_map_event.add('is_scanning_device')

        # Trigger Bug exploitation (go to high-level zone)
        self._handle_siren_bug_reinteract(drop=drop)

        return True

    # ========== CL1 Post-Strategic-Search Hook ==========

    def _after_strategic_search_rescan(self, drop=None):
        """
        [heremei] Hook called in hazard_leveling after run_strategic_search().
        Performs map rescan to detect and process ScanningDevice/Akashi/etc.

        Args:
            drop: DropRecord
        """
        logger.hr('[heremei] Post-strategic-search rescan', level=2)
        self._solved_map_event = set()
        self._solved_fleet_mechanism = False
        self.clear_question()
        self.map_rescan()

    # ========== Core Bug Exploitation ==========

    def _handle_siren_bug_reinteract(self, drop=None):
        """
        [heremei] Core Bug exploitation: jump to high-level zone,
        use ScanningDevice 2 times, then return to CL1.

        Flow:
        1. Read config: SirenBug_Zone, SirenBug_Type
        2. Go to high-level zone via globe
        3. Manually scan map to find ScanningDevice
        4. Select option 2 × 2 times + option 3 × 1 time (use 2 times, don't destroy)
        5. Return to CL1 zone

        Args:
            drop: DropRecord
        """
        # Read config
        try:
            siren_bug_enable = getattr(self.config, 'OpsiSirenBug_SirenBug_Enable', False)
            siren_bug_zone = getattr(self.config, 'OpsiSirenBug_SirenBug_Zone', 0)
            siren_bug_type = getattr(self.config, 'OpsiSirenBug_SirenBug_Type', 'dangerous')
        except Exception as e:
            logger.warning(f'[heremei] Failed to read SirenBug config: {e}')
            return

        # Validate
        if not siren_bug_enable:
            logger.info('[heremei] SirenBug not enabled, skip Bug exploitation')
            return

        try:
            siren_bug_zone = int(siren_bug_zone)
        except (ValueError, TypeError):
            pass

        if not siren_bug_zone:
            logger.info('[heremei] SirenBug_Zone not configured, skip Bug exploitation')
            return

        current_zone_id = self.zone.zone_id
        # Only trigger from CL1 zones (22 and 44 are the two CL1 zones)
        if current_zone_id not in (22, 44):
            logger.warning(f'[heremei] Current zone {current_zone_id} is not CL1, skip Bug exploitation')
            return

        erosion_one_zone = self.name_to_zone(current_zone_id)

        logger.hr('[heremei] SIREN BUG EXPLOITATION', level=1)
        logger.info(f'[heremei] Current: {erosion_one_zone}, Target: {siren_bug_zone}')

        try:
            target_zone = self.name_to_zone(siren_bug_zone)
        except Exception:
            logger.warning(f'[heremei] Cannot resolve SirenBug target zone: {siren_bug_zone}')
            return

        try:
            # Navigate to high-level zone
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                self.os_map_goto_globe(unpin=False)
                self.globe_goto(target_zone, types=(siren_bug_type.upper(),), refresh=True)
                self.zone_init()

                # Manually scan map to find ScanningDevice
                # (Do NOT use auto_search — it would clear the entire zone)
                self.map_init(map_=None)
                camera_queue = self.map.camera_data

                find_device_timer = Timer(30, count=1).start()
                self._solved_map_event = set()
                device_handled = False

                while find_device_timer.reached() is False and not device_handled:
                    # Sweep camera positions
                    if len(camera_queue) == 0:
                        camera_queue = self.map.camera_data
                    camera_queue = camera_queue.sort_by_camera_distance(self.camera)
                    target_camera = camera_queue[0]
                    camera_queue = camera_queue[1:]

                    self.focus_to(target_camera, swipe_limit=(6, 5))
                    self.focus_to_grid_center(0.3)
                    self.device.screenshot()
                    self.update()

                    # Look for ScanningDevice
                    grids = self.view.select(is_scanning_device=True)
                    if grids and grids[0].is_scanning_device \
                            and 'is_scanning_device' not in self._solved_map_event:
                        grid = grids[0]
                        logger.info(f'[heremei] Found ScanningDevice at {grid}')

                        # Walk to device to trigger story popup
                        self.device.click(grid)

                        # Wait for 3 option popup
                        option_wait_timer = Timer(10, count=20).start()
                        options_found = False
                        while not option_wait_timer.reached():
                            self.device.screenshot()
                            options = self._story_option_buttons_2()
                            if len(options) >= 3:
                                logger.info('[heremei] Story options detected, processing Bug exploitation')
                                options_found = True
                                break
                            time.sleep(0.5)

                        if not options_found:
                            logger.warning('[heremei] Timed out waiting for story options')
                            continue

                        self._solved_map_event.add('is_scanning_device')

                        # Use device: option 2 × 2 times, then option 3 × 1 time
                        # (Use 2 times without destroying the device)

                        # 1st use: select option 2 (index 1, purple coins)
                        logger.info('[heremei] Bug exploitation: selecting option 2 (1st time)')
                        time.sleep(1.5)
                        if self._select_story_option_by_index(target_index=1, options_count=3):
                            logger.info('[heremei] Option 2 selected (1st)')
                            time.sleep(0.5)
                            if self._click_story_confirm_button():
                                logger.info('[heremei] Confirmed (1st)')
                        else:
                            logger.warning('[heremei] Failed to select option 2 (1st)')
                            raise RuntimeError('Failed to select option 2 (1st)')

                        # 2nd use: select option 2 (index 1, purple coins)
                        logger.info('[heremei] Bug exploitation: selecting option 2 (2nd time)')
                        time.sleep(2.0)
                        if self._select_story_option_by_index(target_index=1, options_count=3):
                            logger.info('[heremei] Option 2 selected (2nd)')
                            time.sleep(0.5)
                            if self._click_story_confirm_button():
                                logger.info('[heremei] Confirmed (2nd)')
                        else:
                            logger.warning('[heremei] Failed to select option 2 (2nd)')
                            raise RuntimeError('Failed to select option 2 (2nd)')

                        # Leave: select option 3 (index 2, leave)
                        logger.info('[heremei] Bug exploitation: selecting option 3 (leave)')
                        time.sleep(2.0)
                        if self._select_story_option_by_index(target_index=2, options_count=3):
                            logger.info('[heremei] Option 3 selected (leave)')
                            time.sleep(0.5)
                            if self._click_story_confirm_button():
                                logger.info('[heremei] Confirmed (leave)')
                        else:
                            logger.warning('[heremei] Failed to select option 3 (leave)')
                            raise RuntimeError('Failed to select option 3 (leave)')

                        device_handled = True
                        logger.info('[heremei] Bug exploitation complete')

                    time.sleep(0.5)

                if not device_handled:
                    logger.warning(f'[heremei] ScanningDevice not found in zone {siren_bug_zone}')

            # Return to CL1 zone
            logger.info('[heremei] Returning to CL1 zone')
            self.os_map_goto_globe(unpin=False)
            self.globe_goto(erosion_one_zone, types=('SAFE', 'DANGEROUS'), refresh=True)
            logger.info('[heremei] Returned to CL1 zone')

        except Exception as e:
            logger.error(f'[heremei] Bug exploitation failed: {e}', exc_info=True)

            # Try to select leave option if stuck in story popup
            if self._select_story_option_by_index(target_index=2, options_count=3):
                logger.info('[heremei] Error recovery: selected leave option')

            # Return to CL1
            try:
                self.os_map_goto_globe(unpin=False)
                self.globe_goto(erosion_one_zone, types=('SAFE', 'DANGEROUS'), refresh=True)
                logger.info('[heremei] Error recovery: returned to CL1')
            except Exception as return_err:
                logger.error(f'[heremei] Failed to return to CL1: {return_err}')
