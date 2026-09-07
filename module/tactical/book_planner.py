"""Bounded planning for the finite tactical-book stock shown by the game."""

from dataclasses import dataclass


NEXT_XP = (100, 200, 400, 800, 1400, 2200, 3200, 4400, 5800)
SAME_COLOR_XP = {1: 150, 2: 450, 3: 1200, 4: 3000}
BOOK_HOURS = {1: 2, 2: 4, 3: 8, 4: 12}
MAX_REMAINING_XP = 18500


@dataclass(frozen=True)
class BookPlan:
    books: tuple
    total_xp: int
    overflow: int
    total_hours: int
    courses: int
    complete: bool
    reason: str = ''


def remaining_to_level10(current, next_denominator):
    """Return the remaining XP from a normal, unselected skill counter."""
    try:
        current = int(current)
        next_denominator = int(next_denominator)
    except (TypeError, ValueError):
        return None
    if next_denominator not in NEXT_XP or current < 0 or current > next_denominator:
        return None
    index = NEXT_XP.index(next_denominator)
    remaining = next_denominator - current + sum(NEXT_XP[index + 1:])
    return remaining if 0 <= remaining <= MAX_REMAINING_XP else None


def remaining_from_projected_counter(
    white_current, green_projected_remainder, next_denominator, selected_exp
):
    """Undo the currently selected book from the projected skill preview."""
    try:
        white_current = int(white_current)
        green_projected_remainder = int(green_projected_remainder)
        next_denominator = int(next_denominator)
        selected_exp = int(selected_exp)
    except (TypeError, ValueError):
        return None
    if (
        next_denominator not in NEXT_XP
        or min(white_current, green_projected_remainder, selected_exp) < 0
        or white_current + green_projected_remainder >= next_denominator
    ):
        return None
    index = NEXT_XP.index(next_denominator)
    remaining = (
        sum(NEXT_XP[index:])
        - white_current
        - green_projected_remainder
        + selected_exp
    )
    return remaining if 0 <= remaining <= MAX_REMAINING_XP else None


def _value(book):
    tier = getattr(book, 'tier', None)
    if tier is None and isinstance(book, dict):
        tier = book.get('tier')
    try:
        return SAME_COLOR_XP[int(tier)]
    except (KeyError, TypeError, ValueError):
        return None


def _genre(book):
    genre = getattr(book, 'genre', None)
    if genre is None and isinstance(book, dict):
        genre = book.get('genre')
    return genre


def _is_same_color(book, required_genre):
    exp = getattr(book, 'exp', None)
    if exp is None and isinstance(book, dict):
        exp = book.get('exp')
    return bool(exp) and _genre(book) == required_genre and _value(book) is not None


def _count_for(book, index, counts):
    if counts is not None and hasattr(counts, 'get'):
        tier = getattr(book, 'tier', None)
        if tier is None and isinstance(book, dict):
            tier = book.get('tier')
        if tier in counts:
            return counts.get(tier)
        if index in counts:
            return counts.get(index)
    count = getattr(book, 'count', None)
    return count if count is not None else 1


def plan_books(remaining_xp, books, required_genre, counts=None):
    """Choose from finite, same-color book stock.

    Candidates with the same tier are aggregated before the bounded DP. The
    DP only retains sums through ``target + largest_book_value``; this is the
    only overshoot that can be useful for the final book.
    """
    try:
        target = int(remaining_xp)
    except (TypeError, ValueError):
        return BookPlan((), 0, 0, 0, 0, False, 'invalid remaining XP')
    if target < 0 or target > MAX_REMAINING_XP:
        return BookPlan((), 0, 0, 0, 0, False, 'invalid remaining XP')
    if target == 0:
        return BookPlan((), 0, 0, 0, 0, True)
    if required_genre is None:
        return BookPlan((), 0, 0, 0, 0, False, 'skill color is unknown')

    grouped = {}
    for index, book in enumerate(books):
        if not _is_same_color(book, required_genre):
            continue
        tier = int(getattr(book, 'tier', book.get('tier') if isinstance(book, dict) else 0))
        try:
            count = max(0, int(_count_for(book, index, counts)))
        except (TypeError, ValueError):
            count = 0
        if count:
            if tier in grouped:
                previous_book, value, previous_count = grouped[tier]
                if counts is not None and hasattr(counts, 'get') and tier in counts:
                    count = max(previous_count, count)
                else:
                    count += previous_count
                grouped[tier] = (previous_book, value, count)
            else:
                grouped[tier] = (book, _value(book), count)
    if not grouped:
        return BookPlan((), 0, 0, 0, 0, False, 'same-color counts are zero')

    max_value = max(value for _, value, _ in grouped.values())
    limit = target + max_value
    states = {0: (0, 0, ())}
    for book, value, count in sorted(grouped.values(), key=lambda item: item[1]):
        hours = BOOK_HOURS[book.tier]
        next_states = dict(states)
        for total, (previous_hours, previous_courses, chosen) in states.items():
            for copies in range(1, min(count, (limit - total) // value) + 1):
                new_total = total + copies * value
                candidate = (
                    previous_hours + hours * copies,
                    previous_courses + copies,
                    chosen + (book,) * copies,
                )
                previous = next_states.get(new_total)
                if previous is None or candidate[:2] < previous[:2]:
                    next_states[new_total] = candidate
        states = next_states

    complete_totals = [total for total in states if total >= target]
    if complete_totals:
        total = min(complete_totals, key=lambda item: (
            item - target, states[item][0], states[item][1]
        ))
        total_hours, courses, chosen = states[total]
        chosen = tuple(sorted(chosen, key=lambda item: -BOOK_HOURS[item.tier]))
        return BookPlan(chosen, total, total - target, total_hours, courses, True)

    total = max(states, key=lambda item: (item, -states[item][0], -states[item][1]))
    total_hours, courses, chosen = states[total]
    chosen = tuple(sorted(chosen, key=lambda item: -BOOK_HOURS[item.tier]))
    return BookPlan(chosen, total, 0, total_hours, courses, False,
                    'bounded books cannot finish level 10')
