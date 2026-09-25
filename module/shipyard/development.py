"""Safe inspection of the CN Shipyard development task panel."""

from dataclasses import dataclass
import cv2
import json
import re
from pathlib import Path

from module.base.button import Button
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.shipyard.development_assets import (
    HULL_SCULPT_ANCHOR,
    SHIP_NAME_AREA,
    SUPPORTED_SIZE,
    TASK_LIST_AREA,
    TASK_SCAN_ROWS,
    is_task_action_label,
    normalise_cn_task_title,
    ship_name_similarity,
    task_header_button,
    task_identity,
    task_title_area,
)
from module.shipyard.ui import ShipyardUI
from module.shipyard.ui_globals import SHIPYARD_FACE_GRID, SHIPYARD_SERIES_GRID
from module.os.training_policy import parse_training_requirement

TASK_CATALOG = json.loads(Path(__file__).with_name('development_catalog.json').read_text(encoding='utf-8'))['tasks']


@dataclass(frozen=True)
class DevelopmentTask:
    index: int
    title: str
    complete: bool
    header_y: int


class ShipyardDevelopment(ShipyardUI):
    """Inspect an already selected ship without starting or changing research."""

    _ship_name_ocr = Ocr([SHIP_NAME_AREA], lang='cnocr', name='SHIPYARD_DEVELOPMENT_SHIP')

    def _assert_cn_server(self):
        server = getattr(getattr(self, 'config', None), 'SERVER', None)
        if str(server).lower() != 'cn':
            raise ScriptError('Shipyard development requires SERVER=cn')

    def _assert_supported_screen(self):
        image = getattr(self.device, 'image', None)
        shape = getattr(image, 'shape', ())
        if len(shape) < 2 or (shape[1], shape[0]) != SUPPORTED_SIZE:
            raise ScriptError('Shipyard development supports CN 1280x720 only')

    def _working_marker_visible(self):
        text = Ocr([(487, 477, 657, 502)], lang='cnocr', name='WorkingProject').ocr(self.device.image)
        return text.startswith('研究进行中')

    def _read_ship_name(self):
        name = self._ship_name_ocr.ocr(self.device.image).strip()
        if not name or len(name) > 32:
            raise ScriptError('Unknown shipyard working ship name')
        return name

    def _scan_working_ship(self):
        """Scan series and bottom cards, accepting only a visible WORKING tag."""
        if not self._shipyard_in_ui():
            raise ScriptError('Not in the shipyard development screen')

        # The selected page is authoritative.  Only search other series after
        # proving that it is not already the working project.
        if self._working_marker_visible():
            return self._read_ship_name()

        for series in range(1, len(SHIPYARD_SERIES_GRID.buttons) + 1):
            if not self._shipyard_set_series(series, skip_first_screenshot=False):
                continue
            self.device.sleep(0.5)
            self.device.screenshot()
            template = cv2.imread('./assets/cn/shipyard_development/working_label.png', 0)
            if template is None:
                raise ScriptError('Working-project marker asset missing')
            image = cv2.cvtColor(self.device.image[680:720, 180:1275], cv2.COLOR_RGB2GRAY)
            scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, confidence, _, (x, _) = cv2.minMaxLoc(scores)
            if confidence < 0.9:
                continue
            # Select only an actually observed WORKING card, never empty slots.
            center = x + 180 + template.shape[1] // 2
            index = min(6, max(1, (center - 188) // 181 + 1))
            self.shipyard_bottom_navbar_ensure(left=index, skip_first_screenshot=False)
            self.device.sleep(0.5)
            self.device.screenshot()
            if self._working_marker_visible():
                return self._read_ship_name()
        raise ScriptError('No visible working ship found in shipyard series')

    def _ocr_task_title(self, header_y):
        ocr = Ocr([task_title_area(header_y)], lang='cnocr', letter=(214, 225, 235), threshold=128, name='SHIPYARD_DEVELOPMENT_TASK')
        return normalise_cn_task_title(ocr.ocr(self.device.image))

    def _detect_header_ys(self):
        template = cv2.imread('./assets/cn/shipyard_development/target_label.png')
        if template is None:
            raise ScriptError('Shipyard TARGET asset missing')
        template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        image = self.device.image[130:558, 944:1020]
        scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        targets = []
        while scores.max() > 0.65:
            _, _, _, (_, y) = cv2.minMaxLoc(scores)
            targets.append(y + 130 - 6)
            scores[max(0, y - 14):y + 15] = 0
        targets.sort()
        if not targets:
            raise ScriptError('Shipyard task TARGET rows are not identifiable')
        # A red task alert can cover the TARGET label. Two compact rows have
        # a 120-136px pitch here, so probe the one missing header midway and
        # accept it only when its title belongs to a known task family.
        inferred = []
        for upper, lower in zip(targets, targets[1:]):
            if 120 <= lower - upper <= 136:
                header_y = upper + (lower - upper) // 2
                title = self._ocr_task_title(header_y)
                if self._catalog_key(title) is not None or self._is_technical_title(title) \
                        or self._is_known_material_title(title):
                    inferred.append(header_y)
        # TARGET 8 can be covered by its red alert when the last hull row is
        # expanded. The two hull headers still keep their 63px pitch and the
        # second title remains readable (2026-09-25 live submission frame).
        if targets and HULL_SCULPT_ANCHOR in self._ocr_task_title(targets[-1]):
            next_y = targets[-1] + 63
            if next_y + 48 <= TASK_LIST_AREA[3] \
                    and HULL_SCULPT_ANCHOR in self._ocr_task_title(next_y):
                inferred.append(next_y)
        targets = sorted(targets + inferred)
        # TARGET text is at the top of a header.  Keep the offset in one place
        # so a fresh screenshot always produces fresh header coordinates.
        return [y for y in targets if y + 40 <= TASK_LIST_AREA[3]]

    def _task_complete(self, header_y):
        # Complete rows have the green check in the left edge of the header.
        # This is deliberately a color guard, not a generic "non-hourglass"
        # assumption.
        pixels = self.device.image[header_y + 14:header_y + 43, 953:982].astype('int16')
        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        return int(((g > r + 45) & (g > b + 35) & (g > 150)).sum()) > 30

    def _scan_visible_tasks(self, header_ys=None):
        header_ys = self._detect_header_ys() if header_ys is None else header_ys
        tasks = []
        for index, header_y in enumerate(header_ys[:TASK_SCAN_ROWS]):
            title = self._ocr_task_title(header_y)
            if title:
                tasks.append(DevelopmentTask(index + 1, title,
                                              self._task_complete(header_y), header_y))
        # Both hull rows fit together at the bottom of the collapsed CN list.
        # Their suffix OCR is unreliable (II is repeatedly read as I), so the
        # upper/lower visible row is the authoritative stage. A lone hull row
        # has no safe stage identity until both rows are visible together.
        hull_rows = [i for i, task in enumerate(tasks) if HULL_SCULPT_ANCHOR in task.title]
        if len(hull_rows) == 2:
            for stage, i in enumerate(hull_rows, 1):
                task = tasks[i]
                title = re.sub(r'I{1,2}$', '', task.title) + ('I' if stage == 1 else 'II')
                tasks[i] = DevelopmentTask(6 + stage, title, task.complete, task.header_y)
        elif len(hull_rows) == 1:
            i = hull_rows[0]
            task = tasks[i]
            tasks[i] = DevelopmentTask(0, task.title, task.complete, task.header_y)
        return tasks

    def _scroll_task_list(self, direction=-1):
        self.device.swipe_vector(
            (0, direction * 350), box=TASK_LIST_AREA, padding=-5
        )
        self.device.sleep(0.6)
        self.device.screenshot()

    def _collapse_any_expanded_header(self):
        # Re-locate rows from the current screenshot. Exact guard labels
        # prevent a blueprint-strengthen control from being mistaken for this
        # panel.
        ys = self._detect_header_ys()
        for index, header_y in enumerate(ys):
            next_y = ys[index + 1] if index + 1 < len(ys) else TASK_LIST_AREA[3]
            if next_y - header_y > 150 and self._ocr_task_title(header_y):
                self.device.click(task_header_button(header_y))
                self.device.screenshot()
                return True
        return False

    def _read_all_tasks(self):
        """Enumerate bounded viewport states, locating rows on every frame."""
        self._collapse_any_expanded_header()
        for _ in range(2):
            self._scroll_task_list(direction=1)
        seen = {}
        previous = None
        for _ in range(3):
            visible = self._scan_visible_tasks(self._detect_header_ys())
            fingerprint = tuple((self._task_key(t.title), t.complete, t.header_y) for t in visible)
            for task in visible:
                if HULL_SCULPT_ANCHOR in task.title and task.index == 0:
                    continue
                # Rows are keyed by identity, not by raw text: two scans of the
                # same row may differ in a dropped character, and a duplicate
                # key would send the inspector after a title that never exists.
                seen[self._task_key(task.title)] = task
            if len(seen) >= 8 or fingerprint == previous:
                break
            previous = fingerprint
            self._scroll_task_list(direction=-1)
        # Reset to the top after the bottom enumeration before any action.
        for _ in range(1):
            self._scroll_task_list(direction=1)
        visible = self._scan_visible_tasks(self._detect_header_ys())
        for task in visible:
            if HULL_SCULPT_ANCHOR in task.title and task.index == 0:
                continue
            seen[self._task_key(task.title)] = task
        if not seen:
            raise ScriptError('Shipyard task list OCR/state is unknown')
        return list(seen.values())

    @staticmethod
    def _parse_requirement(title):
        """Parse a technical requirement, tolerating a stage OCR dropped.

        A locked row shares its line with the countdown, and the stage stroke
        sitting next to the clock digits is regularly read as part of them
        (``铁血先锋技术测试l69:54:13`` -> ``铁血先锋技术测试``).  The faction and
        position do not depend on the stage, so recovering one still yields the
        requirement the shipyard actually asks for.
        """
        normalised = normalise_cn_task_title(title)
        candidates = [normalised, f'{normalised}I', f'{normalised}II']
        # A stray character left by a misread countdown also has to be trimmed.
        candidates += [normalised[:length]
                       for length in range(len(normalised) - 1, max(1, len(normalised) - 3), -1)]
        for candidate in candidates:
            try:
                return parse_training_requirement(candidate)
            except ValueError:
                continue
        return None

    @staticmethod
    def _pending_requirement(tasks):
        parsed = []
        for task in tasks:
            requirement = ShipyardDevelopment._parse_requirement(task.title)
            if requirement is None:
                continue
            parsed.append((task, requirement))

        incomplete = [(task, req) for task, req in parsed if not task.complete]
        if not incomplete:
            return None

        # Stage I always precedes stage II.  If I is incomplete, return it;
        # stage II is eligible only after a matching I is visibly complete.
        for task, requirement in incomplete:
            if requirement.stage == 1:
                return requirement
        for task, requirement in incomplete:
            if requirement.stage != 2:
                continue
            prerequisite = any(
                other_req.stage == 1
                and other_task.complete
                for other_task, other_req in parsed
            )
            if prerequisite:
                return requirement
        raise ScriptError('Pending technical stage II has no verified completed stage I')

    def _locate_visible_task(self, title):
        """Find a title on the current frame; never reuse historical y data."""
        wanted = self._task_key(title)
        # Earlier submissions/expansions can leave the viewport at the bottom.
        # Searching only downward from there misses task 1 even when it was
        # enumerated successfully at the start of this inspection.
        self._collapse_any_expanded_header()
        for _ in range(2):
            self._scroll_task_list(direction=1)
        for _ in range(8):
            headers = self._detect_header_ys()
            if HULL_SCULPT_ANCHOR in normalise_cn_task_title(title):
                for task in self._scan_visible_tasks(headers):
                    if task.index and self._task_key(task.title) == wanted:
                        return task
            else:
                for header_y in headers:
                    if self._task_key(self._ocr_task_title(header_y)) == wanted:
                        return DevelopmentTask(0, title, False, header_y)
            self._scroll_task_list()
        raise ScriptError(f'Development task is not visible: {title}')

    def _submit_available_task(self, title):
        """Submit only an observed blue 提交 action on a known task row."""
        # Each task is a distinct, bounded inspection.  Reset the device's
        # click-loop history here: scrolling back to the top and opening the
        # first visible header for several rows otherwise looks like the same
        # two-button loop even though each row is inspected once.
        self.device.click_record_clear()
        task = self._locate_visible_task(title)
        self.device.click(task_header_button(task.header_y))
        self.device.sleep(0.6)
        self.device.screenshot()
        # Locate an enabled blue action within the expanded task body. Locked
        # actions are grey and must never become clicks or purchases.
        pixels = self.device.image[210:558, 1080:1245].astype('int16')
        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        mask = ((b > r + 45) & (b > 140) & (g > 75)).astype('uint8') * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rects = [cv2.boundingRect(c) for c in contours]
        rects = [(x, y, w, h) for x, y, w, h in rects if w >= 100 and 25 <= h <= 65]
        if len(rects) != 1:
            logger.info(f'Development task has no available submit action: {title}')
            self._collapse_any_expanded_header()
            return False
        x, y, w, h = rects[0]
        area = (1080 + x, 210 + y, 1080 + x + w, 210 + y + h)
        label = Ocr([area], lang='cnocr', name='DevelopmentSubmit').ocr(self.device.image).strip()
        if not is_task_action_label(label):
            logger.info(f'Development action is not submit: {title}: {label}')
            self._collapse_any_expanded_header()
            return False
        button = Button(area, (0, 0, 0), area, name='SHIPYARD_DEVELOPMENT_SUBMIT')
        self.device.click(button)
        for _ in range(20):
            self.device.sleep(0.3)
            self.device.screenshot()
            if self.handle_popup_confirm('SHIPYARD_DEVELOPMENT'):
                continue
            if self._shipyard_in_ui():
                # The game also offers a blue Submit on time-locked material
                # rows.  Its confirmation succeeds, then a toast says the task
                # is not complete and consumes nothing (seen live on 2026-09-25).
                notice = Ocr([(520, 300, 790, 346)], lang='cnocr',
                             name='DevelopmentSubmitResult').ocr(self.device.image)
                if '任务还没有完成' in notice:
                    logger.info(f'Development task is not yet eligible to submit: {title}')
                    self._collapse_any_expanded_header()
                    return False
                for current in self._scan_visible_tasks():
                    if self._task_key(current.title) == self._task_key(title) and current.complete:
                        self._collapse_any_expanded_header()
                        return True
        if self._shipyard_in_ui():
            logger.warning(f'Development task did not complete after submit; defer: {title}')
            self._collapse_any_expanded_header()
            return False
        raise ScriptError('Development submission left the shipyard unexpectedly')

    def inspect_current_project(self, submit_materials=True):
        """Return the actual working ship and its next technical requirement."""
        self._assert_supported_screen()
        self._assert_cn_server()
        ship_name = self._scan_working_ship()
        # A green check can describe a finished requirement that still needs
        # its separate submit click.  Inspect every known row, not just the
        # rows previously classified as incomplete material requirements.
        for _ in range(TASK_SCAN_ROWS + 1):
            tasks = self._read_all_tasks()
            for task in tasks:
                if not task.complete and self._catalog_kind(task.title) == 'experience' \
                        and not self._is_technical_title(task.title):
                    raise ScriptError(f'Unsupported technical task requirement: {task.title}')
            unknown_incomplete = [
                task for task in tasks
                if not self._is_technical_title(task.title)
                and not task.complete
                and not self._is_known_material_title(task.title)
                and self._catalog_kind(task.title) is None
            ]
            if unknown_incomplete:
                raise ScriptError(f'Unknown shipyard task OCR: {unknown_incomplete[0].title}')

            if submit_materials:
                submitted = False
                for task in tasks:
                    if not (self._is_technical_title(task.title)
                            or self._is_known_material_title(task.title)
                            or self._catalog_kind(task.title) is not None):
                        continue
                    if self._submit_available_task(task.title):
                        submitted = True
                        break
                current_name = self._read_ship_name()
                if current_name != ship_name and ship_name_similarity(current_name, ship_name) < 0.6:
                    raise ScriptError('Working ship changed during development submission')
                if submitted:
                    continue

            requirement = self._pending_requirement(tasks)
            if requirement is not None or not submit_materials:
                self.last_development_tasks = tuple(tasks)
                return ship_name, requirement
            self.last_development_tasks = tuple(tasks)
            return ship_name, None
        raise ScriptError('Development submission state did not settle')

    @staticmethod
    def _is_technical_title(title):
        return ShipyardDevelopment._parse_requirement(title) is not None

    @staticmethod
    def _catalog_key(title):
        """Return the catalogue key a reading belongs to, or None.

        Two kinds of damage are tolerated.  The stage stroke next to the clock
        digits is sometimes read as part of the countdown, so the bare title is
        retried with each stage suffix.  And cnocr occasionally renders the
        countdown's leading digits as a Han character (``先锋技术突破I89:37:17``
        reaches the inspector as ``先锋技术突破I仍:37:17``), which leaves a stray
        character behind once the timer is trimmed; the longest catalogue key
        the reading starts with is accepted for that case.
        """
        normalised = normalise_cn_task_title(title)
        for candidate in (normalised, f'{normalised}I', f'{normalised}II'):
            if candidate in TASK_CATALOG:
                return candidate
        for length in range(len(normalised) - 1, max(1, len(normalised) - 3), -1):
            candidate = normalised[:length]
            if candidate in TASK_CATALOG:
                return candidate
        return None

    @classmethod
    def _catalog_kind(cls, title):
        key = cls._catalog_key(title)
        return TASK_CATALOG[key].get('kind') if key else None

    @classmethod
    def _task_key(cls, title):
        """Stable key for one task row across noisy readings of it.

        Rows are matched and de-duplicated by this key rather than by the raw
        text, so ``先锋技术突破I``, ``先锋技术突破I仍`` and ``先锋技术突破I47:33:43``
        all describe the same row instead of three different ones.
        """
        normalised = normalise_cn_task_title(title)
        if HULL_SCULPT_ANCHOR in normalised:
            return 'hull', 2 if normalised.endswith('II') else 1
        key = cls._catalog_key(title)
        if key is not None:
            return 'catalog', key
        return task_identity(title)

    @classmethod
    def _is_known_material_title(cls, title):
        kind = cls._catalog_kind(title)
        if kind is not None:
            return kind == 'material'
        # A ship released after the catalog snapshot still carries the same
        # hull-sculpting tasks, and the development panel only lists the ship
        # that is being developed, so the ship name itself decides nothing.
        return HULL_SCULPT_ANCHOR in normalise_cn_task_title(title)
