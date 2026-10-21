"""Pure planning rules for rotating submarine training slots in the dorm."""

from module.os.training_policy import (
    ShipCandidate,
    RotationPlan,
    PolicyDecision,
    _valid_candidate,
)


DORM_CAPACITY = range(1, 7)
DORM_AWAKENING_CAPS = frozenset((100, 105, 110, 115))
DORM_TRAINING_COMPLETE_LEVEL = 120


def decide_dorm_trainability(candidate):
    """Apply dorm-specific progress rules without changing tactical training."""
    invalid = _valid_candidate(candidate)
    if invalid:
        return PolicyDecision(False, invalid)
    if candidate.position != 'submarine':
        return PolicyDecision(False, 'ship is not a submarine')
    if not candidate.is_locked:
        return PolicyDecision(False, 'unlocked ship may be limit-break material')
    if candidate.level >= DORM_TRAINING_COMPLETE_LEVEL:
        if candidate.level_cap == 125 and candidate.level < 125:
            return PolicyDecision(True, 'already awakened to 125; train without spending awakening II')
        return PolicyDecision(False, 'dorm training is complete at level 120')
    if candidate.level_cap is None:
        return PolicyDecision(False, 'level cap is unknown')
    if not candidate.is_rainbow and not candidate.fully_limit_broken:
        if candidate.level >= 100:
            return PolicyDecision(False, 'ordinary ship is not fully limit broken at level 100 or higher')
        if candidate.level >= candidate.level_cap:
            return PolicyDecision(False, 'limit break is required to raise the dorm training level cap')
    if candidate.level == candidate.level_cap and candidate.level_cap >= 100 \
            and candidate.stored_exp is None:
        return PolicyDecision(False, 'stored XP is required at level cap 100 or higher')
    return PolicyDecision(True, 'trainable below level 120')


def should_awaken_in_dorm(candidate):
    """Return whether a trainable submarine is ready for dorm awakening."""
    if not isinstance(candidate, ShipCandidate) or candidate.position != 'submarine':
        return False
    if not decide_dorm_trainability(candidate).allowed:
        return False
    return (
        candidate.level_cap in DORM_AWAKENING_CAPS
        and candidate.level == candidate.level_cap
    )


def _failure(current_slots, capacity, reason):
    return RotationPlan(
        False,
        {slot: current_slots.get(slot) for slot in range(1, capacity + 1)},
        reason,
    )


def plan_dorm_rotation(current_slots, candidates, capacity, allow_partial=False):
    """Plan a dorm rotation, optionally retaining completed subs if short on candidates."""
    if capacity not in DORM_CAPACITY:
        return RotationPlan(False, dict(current_slots or {}), 'dorm capacity must be between 1 and 6')
    current_slots = dict(current_slots or {})
    candidates = list(candidates or [])

    if any(slot not in DORM_CAPACITY or slot > capacity for slot in current_slots):
        return _failure(current_slots, capacity, 'dorm slot is outside the selected capacity')

    preserved = {}
    used = set()
    replacements = []
    for slot in range(1, capacity + 1):
        ship = current_slots.get(slot)
        if ship is not None and not isinstance(ship, ShipCandidate):
            return _failure(current_slots, capacity, 'current dorm ship is invalid')
        keep = ship is not None and (
            ship.position != 'submarine' or decide_dorm_trainability(ship).allowed
        )
        if keep:
            if ship.identity in used:
                return _failure(current_slots, capacity, 'duplicate current dorm ship identity')
            preserved[slot] = ship
            used.add(ship.identity)
        else:
            replacements.append(slot)

    eligible = []
    seen = set(used)
    for candidate in candidates:
        if not isinstance(candidate, ShipCandidate):
            continue
        if candidate.position != 'submarine' or not decide_dorm_trainability(candidate).allowed:
            continue
        if candidate.identity in seen:
            continue
        seen.add(candidate.identity)
        eligible.append(candidate)

    if len(eligible) < len(replacements) and not allow_partial:
        return _failure(current_slots, capacity, 'not enough eligible submarines for an atomic rotation')

    result = dict(preserved)
    if allow_partial and len(eligible) < len(replacements):
        # Fill real vacancies first so a shortage never leaves the dorm underfilled.
        empty_slots = [slot for slot in replacements if current_slots.get(slot) is None]
        completed_slots = [slot for slot in replacements if current_slots.get(slot) is not None]
        slots_to_fill = empty_slots + completed_slots[:max(0, len(eligible) - len(empty_slots))]
        for slot, candidate in zip(slots_to_fill, eligible):
            result[slot] = candidate
        for slot in completed_slots[len(slots_to_fill) - len(empty_slots):]:
            result[slot] = current_slots[slot]
    else:
        for slot, candidate in zip(replacements, eligible):
            result[slot] = candidate
    if set(result) != set(range(1, capacity + 1)):
        return _failure(current_slots, capacity, 'dorm rotation did not fill every slot')
    return RotationPlan(True, result)
