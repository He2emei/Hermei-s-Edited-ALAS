"""Daily ten coin catch-ups per rarity, with live prices as the restart ledger."""
from datetime import datetime

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.os.training_ui import CATALOG
from module.shipyard.assets import SHIPYARD_RESEARCH_COMPLETE
from module.shipyard.auto_policy import infer_purchase_offsets, purchase_cost, safe_purchase_amount, server_day
from module.shipyard.auto_ui import AutoShipyardUI, panel_text, panel_next_cost, required_level
from module.shipyard.leveling import ShipyardLeveler
from module.ui.page import page_shipyard


class AutoShipyard(AutoShipyardUI):
    def _offsets(self, rarity):
        """Probe only. Selecting >10 to disambiguate a price never confirms it."""
        if self.auto_set_amount(0) != 0:
            raise RequestHumanTakeover('Cannot reset shipyard price preview')
        _, _, coins = self.auto_observe()
        unit = panel_next_cost(self.device.image, self.auto_fate())
        self.device.screenshot()
        if unit != panel_next_cost(self.device.image, self.auto_fate()):
            raise RequestHumanTakeover('Next unit price is unstable')
        observations, offsets, capacity = [], infer_purchase_offsets(rarity, [(1, unit)]), 0
        if not offsets:
            raise RequestHumanTakeover('Next unit price does not match supported discounts')
        if coins < unit or min(offsets) >= 10:
            return offsets, capacity, coins
        for target in range(1, 16):
            selected = self.auto_set_amount(target)
            if selected < target:
                break
            amount, cost, coins = self.auto_observe()
            if amount != target:
                raise RequestHumanTakeover('Shipyard preview selection changed')
            capacity = amount
            observations.append((amount, cost))
            offsets = tuple(i for i in infer_purchase_offsets(rarity, observations)
                            if i in infer_purchase_offsets(rarity, [(1, unit)]))
            if not offsets:
                raise RequestHumanTakeover(f'Unknown {rarity} catch-up price sequence: {observations}')
            if len(offsets) == 1 or min(offsets) >= 10:
                break
        logger.info(f'Shipyard {rarity} live purchased offsets={offsets}, observations={observations}')
        return offsets, capacity, coins

    def _confirm_purchase(self, rarity, name, offsets, amount):
        if server_day(datetime.now()) != self._day:
            raise RequestHumanTakeover('Shipyard server reset crossed; restart price inspection')
        if self.auto_set_amount(amount) != amount:
            raise RequestHumanTakeover('Shipyard purchase capacity changed')
        selected, cost, coins = self.auto_observe()
        actual = infer_purchase_offsets(rarity, [(selected, cost)])
        if not set(offsets).issubset(actual) or safe_purchase_amount(rarity, offsets, selected, coins) != selected:
            raise RequestHumanTakeover('Shipyard price or daily limit changed before confirmation')
        logger.info(f'Shipyard purchase: {rarity} {name}, count={selected}, coins={cost}, previous={offsets}')
        self._shipyard_buy_confirm('BP_BUY')
        # The selector must reset and the exact displayed coin cost must be
        # deducted. No LastRun is written until the entire rarity reaches ten.
        current, _, remaining = self.auto_observe()
        if current != 0 or remaining != coins - cost:
            raise RequestHumanTakeover('Shipyard confirmation is not verified; re-inspect live prices next run')
        self.device.click_record_clear()
        return tuple(i + selected for i in offsets)

    def _use_owned(self, index):
        """Do not count existing blueprints as free coin catch-up purchases."""
        for _ in range(40):
            before = self._shipyard_get_bp_count(index)
            if before == 0:
                return True
            if not 0 < before <= 3000:
                raise RequestHumanTakeover('Unknown owned shipyard blueprint count')
            if required_level(self.device.image, self.auto_fate()) or self.auto_full():
                return False
            selected = self.auto_set_amount(before)
            if selected <= 0:
                return False
            self._shipyard_buy_confirm('BP_USE')
            after = self._shipyard_get_bp_count(index)
            if after != before - selected:
                raise RequestHumanTakeover('Owned blueprint deduction did not match preview')
            self.device.click_record_clear()
            if not self.auto_enter():
                return False
        raise RequestHumanTakeover('Owned blueprint use exceeded bounded progress')

    def _candidate(self, series, index, name, rarity, allow_level):
        for _ in range(12):  # Development gates are bounded by levels 10..100.
            if not self.auto_enter():
                return 'unbuilt'
            gate = required_level(self.device.image, self.auto_fate())
            if gate:
                if not allow_level or not self.config.ShipyardAuto_UseExpBooks:
                    return 'level'
                leveler = ShipyardLeveler(self.config, self.device)
                if not leveler.meet_level(name, gate):
                    self.ui_ensure(page_shipyard)
                    return 'books'
                self.ui_ensure(page_shipyard)
                self.shipyard_set_focus(series, index)
                if self.auto_name() != name:
                    return 'moved'
                continue
            if self.auto_full():
                return 'full'
            if not self._use_owned(index):
                if required_level(self.device.image, self.auto_fate()):
                    continue
                return 'full' if self.auto_full() else 'retry'
            if panel_text(self.device.image, self.auto_fate()) != '物资':
                return 'unavailable'
            offsets, capacity, coins = self._offsets(rarity)
            if min(offsets) >= 10:
                self.auto_set_amount(0)
                return 'done'
            # Once the offset is known, obtain the actual capacity up to today's
            # remaining limit. A ship can stop at an intermediate level gate.
            capacity = self.auto_set_amount(max(0, 10 - max(offsets)))
            amount = safe_purchase_amount(rarity, offsets, capacity, coins)
            if not amount:
                self.auto_set_amount(0)
                return 'coins' if coins < min(purchase_cost(rarity, i, 1) for i in offsets) else 'ambiguous'
            after = self._confirm_purchase(rarity, name, offsets, amount)
            logger.info(f'Shipyard {rarity}: confirmed daily total range {min(after)}..{max(after)} / 10')
            if min(after) >= 10:
                return 'done'
        return 'retry'

    def run_auto(self):
        self.device.screenshot()
        if self.config.SERVER != 'cn' or self.device.image.shape[:2] != (720, 1280):
            raise RequestHumanTakeover('Automatic shipyard requires CN 1280x720')
        self._day = server_day(datetime.now())
        self.ui_ensure(page_shipyard)
        # Follow upstream's supported PR/DR series lists; live material labels
        # still decide eligibility. Do not infer a ship's rarity from its slot.
        supported = {r: self.config.args['Shipyard'][group]['ResearchSeries']['option']
                     for r, group in (('PR', 'Shipyard'), ('DR', 'ShipyardDr'))}
        done, blocked, deferred, skipped = set(), set(), [], []
        needs_level = set()
        for rarity, field in (('DR', 'DrLastRun'), ('PR', 'PrLastRun')):
            last = getattr(self.config, 'ShipyardAuto_' + field)
            if server_day(last) == self._day:
                done.add(rarity)
        for allow_level in (False, True):
            # First prefer ships that already meet the level requirement.
            for series in sorted(set(supported['PR'] + supported['DR'])):
                if len(done | blocked) == 2:
                    break
                self._shipyard_set_series(series)
                for index in range(1, 7 if series <= 2 else 6):
                    if len(done | blocked) == 2:
                        break
                    self.shipyard_bottom_navbar_ensure(left=index)
                    name = self.auto_name()
                    if name is None:
                        deferred.append(f'{series}/{index}: unknown identity')
                        continue
                    self.device.click_record_clear()  # verified new ship focus
                    rarity = 'DR' if CATALOG[name]['rarity'] == 6 else 'PR'
                    if rarity in done | blocked or series not in supported[rarity]:
                        continue
                    if allow_level and name not in needs_level:
                        continue
                    if self.appear(SHIPYARD_RESEARCH_COMPLETE, offset=(20, 20)):
                        skipped.append(name + ': awaiting construction claim')
                        continue
                    result = self._candidate(series, index, name, rarity, allow_level)
                    logger.info(f'Shipyard candidate: series={series}, slot={index}, {rarity}, {name}: {result}')
                    if result == 'done':
                        done.add(rarity)
                        field = 'DrLastRun' if rarity == 'DR' else 'PrLastRun'
                        setattr(self.config, 'ShipyardAuto_' + field, datetime.now().replace(microsecond=0))
                    elif result == 'coins':
                        blocked.add(rarity)
                        deferred.append(name + ': coins')
                    elif result not in ('full', 'unbuilt', 'unavailable', 'level') or (result == 'level' and allow_level):
                        deferred.append(name + ': ' + result)
                    else:
                        skipped.append(name + ': ' + result)
                        if result == 'level':
                            needs_level.add(name)
            if len(done | blocked) == 2:
                break
        logger.info(f'Shipyard auto summary: completed={sorted(done)}, deferred={deferred}, skipped={skipped}')
        if deferred and len(done) < 2:
            self.config.task_delay(minute=60)
        else:
            self.config.task_delay(server_update=True)
