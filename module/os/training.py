"""CN fourth-fleet training maintenance, invoked only by hazard-one leveling."""
import time

import cv2

from module.base.utils import crop
from module.exception import RequestHumanTakeover
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.logger import logger
from module.ocr.ocr import Ocr
from module.os.training_policy import ROTATION_SLOTS, decide_trainability, plan_rotation, should_awaken
from module.os.deployment_cost import read_deployment_cost
from module.os.training_ui import (TrainingShipInspector, DOCK_SCROLL,
                                   FILTER_FACTIONS, catalog_name, point_button, dock_cards,
                                   same_dock_page)
from module.retire.assets import DOCK_CHECK
from module.retire.dock import OCR_DOCK_SELECTED
from module.os_handler.port import PORT_CHECK
from module.ui.page import page_shipyard


class TrainingFleetManager(TrainingShipInspector):
    def _wait(self, predicate, description):
        for _ in range(40):
            self.device.screenshot()
            if predicate():
                self.device.sleep(0.6)
                self.device.screenshot()
                if predicate():
                    return
            self.device.sleep(0.15)
        raise RequestHumanTakeover('Training UI timeout: ' + description)

    def _label(self, area):
        return Ocr([area], lang='cnocr', name='TrainingGuard').ocr(self.device.image).replace(' ', '')

    def _one_ship_selected(self):
        current, _, total = OCR_DOCK_SELECTED.ocr(self.device.image)
        return current == 1 and total == 1

    def _is_selector(self):
        template = cv2.cvtColor(cv2.imread('./assets/cn/opsi_training/fleet_selector_title.png'), cv2.COLOR_BGR2RGB)
        return cv2.matchTemplate(crop(self.device.image, (120, 65, 320, 120)), template,
                                 cv2.TM_CCOEFF_NORMED).max() > 0.9

    def _fourth_row_y(self):
        template = cv2.imread('./assets/cn/opsi_training/fleet_four_label.png')
        if template is None:
            raise RequestHumanTakeover('Fourth fleet label asset missing')
        template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        scores = cv2.matchTemplate(crop(self.device.image, (214, 140, 345, 543)), template,
                                   cv2.TM_CCOEFF_NORMED)
        _, confidence, _, (_, y) = cv2.minMaxLoc(scores)
        if confidence < 0.9:
            raise RequestHumanTakeover('Cannot locate fourth fleet row')
        return y + 140 + 21

    def _open_selector(self, opsi):
        opsi.ensure_no_map_event()
        opsi.order_enter()
        if self._label((975, 134, 1130, 167)) != '舰队部署':
            raise RequestHumanTakeover('Fleet deployment command unavailable')
        self.device.click(point_button(1065, 164, 'TRAINING_DEPLOY_ENTER'))
        self._wait(self._is_selector, 'fleet selector')
        self.device.swipe_vector((0, -300), box=(700, 190, 880, 500))
        self.device.sleep(0.6)
        self.device.screenshot()
        self._fourth_row_y()

    def _close_selector(self, opsi):
        if not self._is_selector():
            raise RequestHumanTakeover('Cannot safely close unknown fleet UI')
        self.device.click(point_button(1143, 94, 'TRAINING_SELECTOR_CLOSE'))
        self._wait(opsi.is_in_map, 'return to NY')

    def _open_slot(self, slot, target=None):
        if slot not in ROTATION_SLOTS or not self._is_selector():
            raise RequestHumanTakeover('Attempt to edit an immutable slot or unknown UI')
        y = self._fourth_row_y()
        self.device.click(point_button((414, 517, 620, 729, 833, 934)[slot - 1], y,
                                       'TRAINING_SLOT_' + str(slot)))
        self._wait(lambda: self.appear(DOCK_CHECK, offset=(20, 20)), 'deployment ship dock')
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set(True)
        self.dock_filter_set(index='all', faction=FILTER_FACTIONS.get(target.faction, 'other') if target else 'all')
        DOCK_SCROLL.set_top(main=self)

    def _cancel_slot(self):
        self.device.click(point_button(808, 670, 'TRAINING_SHIP_CANCEL'))
        self._wait(self._is_selector, 'cancel ship selection')

    def _visible_names(self):
        self._visible_cards = dock_cards(self.device.image)
        areas = [(b.area[0], b.area[1] + 164, b.area[2], b.area[1] + 189)
                 for b in self._visible_cards]
        if not areas:
            raise RequestHumanTakeover('Deployment dock cards are not identifiable')
        # Keep the raw readings too: the scan compares them between screenshots
        # to tell a page turn from a stuck swipe.
        self._raw_names = Ocr(areas, lang='cnocr', name='TrainingAvailableNames').ocr(self.device.image)
        return [catalog_name(n) for n in self._raw_names]

    def _scan_selection(self, target=None):
        names = set()
        previous_reading = None
        position = None
        for _ in range(40):
            self.device.screenshot()
            visible = self._visible_names()
            new_names = {n for n in visible if n is not None} - names
            if new_names:
                # A recognized new page is actual progress, not a stuck swipe.
                # Keep the hard page bound and repeated-page check below.
                self.device.click_record_clear()
            for button, name in zip(self._visible_cards, visible):
                if name is not None:
                    names.add(name)
                if target is not None and name == target:
                    return button
            current = DOCK_SCROLL.cal_position(main=self)
            if current > 1 - DOCK_SCROLL.edge_threshold:
                # Same judgement as DOCK_SCROLL.at_bottom(), on the position
                # this round has already measured.
                break
            if previous_reading is not None and not new_names \
                    and same_dock_page(previous_reading, self._raw_names):
                # The same cards are printed again. cnocr never reads a page
                # twice the same way, so this is a tolerant comparison rather
                # than an exact one.
                logger.info('Deployment dock page repeated after scrolling, stop')
                break
            if position is not None and not (current - position >= DOCK_SCROLL.drag_threshold):
                # The scrollbar does not advance any more. This is how the
                # deployment dock ends: its thumb bottoms out at 0.945 of the
                # calibrated track (the area runs past the end of the track),
                # so at_bottom() never fires and Scroll.set() alone would keep
                # swiping at an unreachable position until the click guard
                # aborted the task.
                logger.info('Deployment dock cannot scroll further, the list ends here')
                break
            previous_reading, position = self._raw_names, current
            DOCK_SCROLL.next_page(main=self, page=0.45)
            self.device.sleep(0.6)
        if target is not None:
            raise RequestHumanTakeover('Planned ship is not available in deployment dock: ' + target)
        return names

    def _available_ships(self, opsi):
        self._open_selector(opsi)
        available = set()
        for slot in (2, 5):
            self._open_slot(slot)
            available.update(self._scan_selection())
            self._cancel_slot()
        self._close_selector(opsi)
        return available

    def _awaken_planned_ship(self, target):
        # Search the regular dock; deployment selection does not open details.
        from module.ui.page import page_dock
        self.ui_ensure(page_dock)
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set(True)
        self.dock_filter_set(index=target.position, faction=FILTER_FACTIONS.get(target.faction, 'all'))
        DOCK_SCROLL.set_top(main=self)
        button = self._scan_selection(target.name)
        self.ship_info_enter(button, long_click=False)
        actual = self.read_ship()
        if actual != target:
            raise RequestHumanTakeover('Ship changed since planning; awakening deferred')
        return self.awaken_for_training(actual)

    def _deploy(self, opsi, current, planned):
        changed = [slot for slot in ROTATION_SLOTS if current[slot].name != planned[slot].name]
        if not changed:
            return
        self._open_selector(opsi)
        y = self._fourth_row_y()
        anchors = [crop(self.device.image, (x - 25, y - 24, x + 25, y + 24), copy=True)
                   for x in (414, 729)]
        # Preflight every selected identity before making the first edit.
        for slot in changed:
            self._open_slot(slot, planned[slot])
            button = self._scan_selection(planned[slot].name)
            self.device.click(button)
            self.device.sleep(0.6)
            self.device.screenshot()
            if not self._one_ship_selected():
                raise RequestHumanTakeover('Planned ship cannot be selected; fleet edits have not started')
            self._cancel_slot()
        for slot in changed:
            self._open_slot(slot, planned[slot])
            button = self._scan_selection(planned[slot].name)
            self.device.click(button)
            self.device.sleep(0.5)
            self.device.screenshot()
            if not self._one_ship_selected():
                raise RequestHumanTakeover('Deployment selected count is not exactly one')
            self.device.click(point_button(1030, 670, 'TRAINING_SHIP_CONFIRM'))
            self._wait(self._is_selector, 'ship selection confirmation')
            logger.info(f'Training draft slot {slot}: {current[slot].name} -> {planned[slot].name}')
        y = self._fourth_row_y()
        for x, before in zip((414, 729), anchors):
            after = crop(self.device.image, (x - 25, y - 24, x + 25, y + 24))
            if cv2.matchTemplate(after, before, cv2.TM_CCOEFF_NORMED).max() < 0.95:
                raise RequestHumanTakeover('Protected fleet portrait changed; deployment stopped')
        if self._label((970, 584, 1155, 621)) != '立刻前往':
            raise RequestHumanTakeover('Deployment confirmation is unknown')
        self.device.click(point_button(1060, 608, 'TRAINING_DEPLOY_CONFIRM'))
        self._wait(lambda: self.appear(POPUP_CANCEL, offset=(20, 20))
                   and self.appear(POPUP_CONFIRM, offset=(20, 20)),
                   'deployment cost confirmation')
        cost = read_deployment_cost(self.device.image)
        if cost != 0:
            logger.warning(f'Training deployment deferred until free (displayed AP cost: {cost})')
            if not self.handle_popup_cancel('OPSI_TRAINING_DEPLOY_PAID'):
                raise RequestHumanTakeover('Could not cancel paid deployment')
            self._wait(self._is_selector, 'return to fleet selector after cost cancellation')
            self._close_selector(opsi)
            return False
        self.device.click(POPUP_CONFIRM)
        def deployed():
            if self.appear(PORT_CHECK, offset=(20, 20)):
                opsi.port_quit()
                return False
            return opsi.is_in_map()
        self._wait(deployed, 'deployment completion')
        actual = self.inspect_map_fleet(opsi)
        if any(actual[s].name != planned[s].name for s in range(1, 7)):
            raise RequestHumanTakeover('Deployed ship identities differ from the full plan')
        if any(not decide_trainability(actual[s]).allowed for s in ROTATION_SLOTS):
            raise RequestHumanTakeover('A deployed ship no longer meets training requirements')
        logger.info('Fourth fleet deployment verified, both anchors preserved')
        return True

    def maintain(self, opsi):
        from module.shipyard.development import ShipyardDevelopment
        self._check_cn()
        if self.config.OpsiFleet_Fleet != 4:
            raise RequestHumanTakeover('Training maintenance requires hazard-one fleet 4')
        self.ui_ensure(page_shipyard)
        shipyard = ShipyardDevelopment(self.config, self.device)
        ship_name, requirement = shipyard.inspect_current_project(submit_materials=True)
        logger.info(f'Training development project: {ship_name}: {requirement}')
        opsi.os_init(skip_first_auto_search=True)
        opsi.globe_goto(opsi.name_to_zone('NY'))
        current = self.inspect_map_fleet(opsi)
        requirements = {slot: requirement if requirement and requirement.position == ('main' if slot < 4 else 'vanguard')
                        else None for slot in ROTATION_SLOTS}
        initial = plan_rotation(requirements, current, [])
        candidates = []
        search = {}
        for side, slots in (('main', (2, 3)), ('vanguard', (5, 6))):
            existing = [current[slot] for slot in slots if decide_trainability(current[slot]).allowed]
            active = requirement if requirement and requirement.position == side else None
            rainbow = any(ship.is_rainbow for ship in existing)
            matching_rainbow = any(ship.is_rainbow and ship.faction in active.factions
                                   for ship in existing) if active else rainbow
            faction_count = sum(ship.faction in active.factions for ship in existing) if active else 0
            search[side] = (len(existing) < 2 or not rainbow
                            or active is not None and (not matching_rainbow or faction_count < 2))
        if not initial.success or any(search.values()):
            available = self._available_ships(opsi)
            excluded = {ship.name for ship in current.values()}
            for side, slots in (('main', (2, 3)), ('vanguard', (5, 6))):
                if not search[side] and initial.success:
                    continue
                existing = [current[slot] for slot in slots if decide_trainability(current[slot]).allowed]
                active = requirement if requirement and requirement.position == side else None
                factions = active.factions if active else frozenset()
                has_matching_rainbow = any(ship.is_rainbow and (not active or ship.faction in factions)
                                           for ship in existing)
                rainbow_candidates = []
                if not has_matching_rainbow:
                    rainbow_candidates = self.find_candidates(
                        side, factions, excluded, needed=1, available=available, rarity='ultra')
                    candidates.extend(rainbow_candidates)
                if not rainbow_candidates and not any(ship.is_rainbow for ship in existing):
                    candidates.extend(self.find_candidates(
                        side, frozenset(), excluded, needed=1, available=available, rarity='ultra'))
                faction_count = sum(ship.faction in factions for ship in existing) if active else 0
                if len(existing) < 2 or active and faction_count < 2:
                    candidates.extend(self.find_candidates(
                        side, factions, excluded, needed=2, available=available))
        plan = plan_rotation(requirements, current, candidates)
        if not plan.success:
            raise RequestHumanTakeover('No complete eligible fleet plan: ' + plan.reason)
        logger.info('Training plan: ' + ', '.join(f'{s}={plan.slots[s].name}' for s in range(1, 7)))
        completed_during_awaken = False
        for slot in ROTATION_SLOTS:
            if should_awaken(plan.slots[slot]):
                plan.slots[slot] = self._awaken_planned_ship(plan.slots[slot])
                if not decide_trainability(plan.slots[slot]).allowed:
                    logger.info(f'Training ship reached its target during awakening: {plan.slots[slot].name}')
                    completed_during_awaken = True
                    break
        opsi.os_init(skip_first_auto_search=True)
        opsi.globe_goto(opsi.name_to_zone('NY'))
        if not completed_during_awaken:
            self._deploy(opsi, current, plan.slots)
        self.config.cross_set(keys='OpsiHazard1Leveling.OpsiTraining.LastCheck', value=int(time.time()))
