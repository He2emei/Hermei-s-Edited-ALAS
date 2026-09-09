"""Pure planning rules for rotating submarine training slots in the dorm."""

from module.os.training_policy import (
    ShipCandidate,
    RotationPlan,
    decide_trainability,
)


DORM_CAPACITY = range(1, 7)
DORM_AWAKENING_CAPS = frozenset((100, 105, 110, 115))


def should_awaken_in_dorm(candidate):
    """Return whether a trainable submarine is ready for dorm awakening."""
    if not isinstance(candidate, ShipCandidate) or candidate.position != 'submarine':
        return False
    if not decide_trainability(candidate).allowed:
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


def plan_dorm_rotation(current_slots, candidates, capacity):
    """Plan an atomic dorm rotation, preserving eligible subs and non-subs."""
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
            ship.position != 'submarine' or decide_trainability(ship).allowed
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
        if candidate.position != 'submarine' or not decide_trainability(candidate).allowed:
            continue
        if candidate.identity in seen:
            continue
        seen.add(candidate.identity)
        eligible.append(candidate)

    if len(eligible) < len(replacements):
        return _failure(current_slots, capacity, 'not enough eligible submarines for an atomic rotation')

    result = dict(preserved)
    for slot, candidate in zip(replacements, eligible):
        result[slot] = candidate
    if set(result) != set(range(1, capacity + 1)):
        return _failure(current_slots, capacity, 'dorm rotation did not fill every slot')
    return RotationPlan(True, result)
