"""Pure policy for tactical training and fourth-fleet rotation planning."""

from dataclasses import dataclass
import re
from typing import Optional


MAX_LEVEL = 125
MAX_STORED_EXP = 3_000_000
ROTATION_SLOTS = (2, 3, 5, 6)
MAIN_SLOTS = (2, 3)
VANGUARD_SLOTS = (5, 6)

# These are deliberately exact labels.  Unknown text is rejected instead of
# being guessed as a faction, which matters when OCR produces a plausible but
# unsupported title.
CANONICAL_FACTIONS = frozenset({
    '皇家', '铁血', '重樱', '白鹰', '东煌', '北联',
    '撒丁帝国', '自由鸢尾', '维希教廷',
    'META', '联动',
    '郁金王国', '晶石联盟', '飓风',
})


@dataclass(frozen=True)
class ShipCandidate:
    name: str
    faction: str
    position: str
    level: int
    is_rainbow: bool
    fully_limit_broken: bool
    stored_exp: Optional[int] = None
    level_cap: Optional[int] = None

    @property
    def identity(self):
        """Stable identity used for de-duplication across fleets and slots."""
        return self.name


@dataclass(frozen=True)
class TrainingRequirement:
    factions: frozenset
    position: str
    stage: int
    title: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RotationPlan:
    success: bool
    slots: dict
    reason: str = ''


def _valid_candidate(candidate):
    if not isinstance(candidate, ShipCandidate):
        return 'invalid ship candidate'
    if not candidate.name or not isinstance(candidate.name, str):
        return 'ship identity is unknown'
    if candidate.faction not in CANONICAL_FACTIONS:
        return 'ship faction is unknown'
    if candidate.position not in ('main', 'vanguard', 'submarine'):
        return 'ship position is unknown'
    if not isinstance(candidate.is_rainbow, bool):
        return 'rainbow flag is unknown'
    if not isinstance(candidate.fully_limit_broken, bool):
        return 'limit break state is unknown'
    if (
        not isinstance(candidate.level, int)
        or isinstance(candidate.level, bool)
        or not 1 <= candidate.level <= MAX_LEVEL
    ):
        return 'ship level is invalid'
    if candidate.level_cap is not None and (
        not isinstance(candidate.level_cap, int)
        or isinstance(candidate.level_cap, bool)
        or not 1 <= candidate.level_cap <= MAX_LEVEL
        or candidate.level_cap < candidate.level
    ):
        return 'ship level cap is invalid'
    if candidate.stored_exp is not None and (
        not isinstance(candidate.stored_exp, int)
        or isinstance(candidate.stored_exp, bool)
        or not 0 <= candidate.stored_exp <= MAX_STORED_EXP
    ):
        return 'stored XP is unknown or invalid'
    return None


def decide_trainability(candidate):
    """Return whether a ship is safe to send to tactical training."""
    invalid = _valid_candidate(candidate)
    if invalid:
        return PolicyDecision(False, invalid)
    if candidate.level == MAX_LEVEL:
        return PolicyDecision(False, 'level 125 is complete')
    if not candidate.is_rainbow and not candidate.fully_limit_broken:
        return PolicyDecision(False, 'ordinary ship is not fully limit broken')

    level_cap = candidate.level_cap
    at_current_cap = level_cap is not None and candidate.level == level_cap
    if level_cap is None:
        if candidate.level >= 100:
            return PolicyDecision(False, 'level cap is unknown at an ambiguous level')
    elif at_current_cap and level_cap >= 100:
        if candidate.stored_exp is None:
            return PolicyDecision(False, 'stored XP is required at level cap 100 or higher')
        if candidate.level >= (115 if candidate.is_rainbow else 110) \
                and candidate.stored_exp >= MAX_STORED_EXP:
            return PolicyDecision(False, 'stored XP and level threshold are complete')
    return PolicyDecision(True, 'trainable')


def is_trainable(candidate):
    return decide_trainability(candidate).allowed


def decide_awaken(candidate):
    """Return whether the current level cap requires an awakening step."""
    invalid = _valid_candidate(candidate)
    if invalid:
        return PolicyDecision(False, invalid)
    if not candidate.is_rainbow and not candidate.fully_limit_broken:
        return PolicyDecision(False, 'ordinary ship is not fully limit broken')
    if candidate.level_cap is None:
        return PolicyDecision(False, 'level cap is unknown')
    allowed_caps = {100, 105, 110, 115} if candidate.is_rainbow else {100, 105}
    if candidate.level_cap not in allowed_caps:
        return PolicyDecision(False, 'this level cap does not require awakening')
    if candidate.level != candidate.level_cap:
        return PolicyDecision(False, 'ship has not reached its current level cap')
    return PolicyDecision(True, 'awakening required')


def should_awaken(candidate):
    return decide_awaken(candidate).allowed


def _normalise_title(title):
    if not isinstance(title, str):
        raise ValueError('training title is unknown')
    title = re.sub(r'\s+', '', title)
    return title.translate(str.maketrans({'Ⅰ': 'I', 'Ⅱ': 'II'}))


def _parse_faction_union(text):
    if not text:
        raise ValueError('training title has no explicit faction')
    for separator in ('、', '/', '+', '&', ',', '和', '及'):
        text = text.replace(separator, '|')
    parts = [part for part in text.split('|') if part]
    if not parts or any(part not in CANONICAL_FACTIONS for part in parts):
        raise ValueError('training title contains an unknown faction')
    return frozenset(parts)


def parse_training_requirement(title):
    """Parse titles such as ``皇家先锋技术测试I`` without guessing."""
    normalised = _normalise_title(title)
    match = re.fullmatch(r'(.+?)(先锋|主力)技术测试(II|I)', normalised)
    if not match:
        raise ValueError('training title format or stage is unknown')
    factions = _parse_faction_union(match.group(1))
    position = 'vanguard' if match.group(2) == '先锋' else 'main'
    stage = 2 if match.group(3) == 'II' else 1
    return TrainingRequirement(factions, position, stage, title)


parse_research_requirement = parse_training_requirement


def _requirement_matches(candidate, requirement, slot):
    side = 'main' if slot in MAIN_SLOTS else 'vanguard' if slot in VANGUARD_SLOTS else None
    if side is None or not is_trainable(candidate) or candidate.position != side:
        return False
    if requirement is None:
        return True
    return requirement.position == side and candidate.faction in requirement.factions


def plan_rotation(requirements, current_slots, screen_candidates, excluded_identities=()):
    """Plan slots 2/3/5/6 atomically, preserving eligible current ships."""
    requirements = dict(requirements or {})
    current_slots = dict(current_slots or {})
    screen_candidates = list(screen_candidates or [])
    excluded = set(excluded_identities or ())

    for slot in requirements:
        if slot not in ROTATION_SLOTS:
            return RotationPlan(False, dict(current_slots), f'slot {slot} is immutable or invalid')
    # All four rotation slots are planned together. A missing or None entry is
    # an unrestricted requirement for that slot, not permission to leave it
    # empty or to accept an unsuitable ship.
    requirements = {slot: requirements.get(slot) for slot in ROTATION_SLOTS}
    for slot, requirement in requirements.items():
        if requirement is not None and not isinstance(requirement, TrainingRequirement):
            return RotationPlan(False, dict(current_slots), f'slot {slot} has an invalid requirement')

    assignments = dict(current_slots)
    for slot in (1, 4) + ROTATION_SLOTS:
        assignments.setdefault(slot, None)
    slot_order = list(ROTATION_SLOTS)
    other_current = {
        candidate.identity for slot, candidate in current_slots.items()
        if slot not in slot_order and isinstance(candidate, ShipCandidate)
    }

    def options(slot, used):
        current = current_slots.get(slot)
        result = []
        if (
            current is not None
            and current.identity not in excluded
            and current.identity not in other_current
            and _requirement_matches(current, requirements[slot], slot)
        ):
            result.append(current)
        for candidate in screen_candidates:
            if candidate.identity == (current.identity if current else None):
                continue
            if candidate.identity in excluded or candidate.identity in other_current or candidate.identity in used:
                continue
            if _requirement_matches(candidate, requirements[slot], slot):
                result.append(candidate)
        return result

    def search(index, used):
        if index == len(slot_order):
            return dict(assignments)
        slot = slot_order[index]
        current = current_slots.get(slot)
        next_used = used
        for candidate in options(slot, next_used):
            if candidate.identity in next_used:
                continue
            assignments[slot] = candidate
            result = search(index + 1, next_used | {candidate.identity})
            if result is not None:
                return result
        if current is None:
            assignments.pop(slot, None)
        return None

    result = search(0, set(other_current) | excluded)
    if result is None:
        return RotationPlan(False, dict(current_slots), 'requirements cannot be satisfied without duplicate or side mismatch')
    return RotationPlan(True, result)
