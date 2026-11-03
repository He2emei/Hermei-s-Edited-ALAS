"""Pure policy for monthly medal shop purchases.

This module intentionally has no UI or game-state dependencies. Unknown item
names are never treated as ordinary purchasable goods.
"""

import re
from collections.abc import Mapping
from pathlib import Path


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / 'assets' / 'shop' / 'medal'
try:
    _TEMPLATE_NAMES = frozenset(path.stem for path in _TEMPLATE_DIR.glob('*.png'))
except OSError:
    _TEMPLATE_NAMES = frozenset()

_VARIANT_SUFFIX = re.compile(r'^(.*)_([0-9]+)$')
_RETROFIT_CHOICES = frozenset(('dd', 'cl', 'bb', 'cv'))
_PLATE_CHOICES = frozenset(('general', 'gun', 'torpedo', 'antiair', 'plane'))
_SELECT_CHOICES = _RETROFIT_CHOICES | _PLATE_CHOICES


def _positive_or_zero_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('{} must be a non-negative integer'.format(label))
    return value


def _canonical_name(name):
    """Return a known template's canonical name, or None for unknown input."""
    if not isinstance(name, str):
        return None
    if name not in _TEMPLATE_NAMES:
        return None
    match = _VARIANT_SUFFIX.match(name)
    if match and match.group(1) in _TEMPLATE_NAMES:
        return match.group(1)
    return name


def priority(name):
    """Return the monthly purchase rank, or None for unknown/protected items.

    Lower ranks are purchased first. Known ship entries are deliberately
    excluded, including both current SSR ship-selection tickets.
    """
    canonical = _canonical_name(name)
    if canonical is None or canonical.startswith('Ship'):
        return None

    if canonical.startswith('SpecializedCore'):
        return 0
    if canonical.startswith('BulinT2'):
        return 1
    if canonical.startswith('BulinT1'):
        return 2
    if canonical.startswith('DR'):
        return 3
    if canonical.startswith('Retrofit') and canonical.endswith('T3'):
        return 4
    if canonical.startswith('Retrofit') and canonical.endswith('T2'):
        return 5
    if canonical.startswith('Plate') and canonical.endswith('T3'):
        return 6
    if canonical.startswith('Plate') and canonical.endswith('T1'):
        return 7
    if canonical.startswith('Book') and canonical.endswith('T3'):
        return 8
    if canonical.startswith('PR'):
        return 9
    if canonical.startswith('Book') and canonical.endswith('T2'):
        return 10
    return 11


def balanced_choice(stock, affordable, choices, counts):
    """Choose a valid selection-box option and a quantity that balances it.

    ``stock`` and ``affordable`` are item quantities, not currency amounts.
    Choices must be a non-empty, unique subset of either retrofit or plate
    options. Stable input order breaks ties. The returned quantity spreads an
    available batch across tied options, stopping at the next higher count.
    """
    stock = _positive_or_zero_int(stock, 'stock')
    affordable = _positive_or_zero_int(affordable, 'affordable')
    if not isinstance(choices, (list, tuple)):
        raise ValueError('choices must be a list or tuple')
    if not choices or any(not isinstance(choice, str) for choice in choices):
        raise ValueError('choices must contain valid option names')
    if len(set(choices)) != len(choices):
        raise ValueError('choices must be unique')
    if not (set(choices) <= _RETROFIT_CHOICES or set(choices) <= _PLATE_CHOICES):
        raise ValueError('choices must belong to one selection-box family')
    if not isinstance(counts, Mapping):
        raise ValueError('counts must be a mapping')
    if any(key not in _SELECT_CHOICES for key in counts):
        raise ValueError('counts contains an unknown option')
    for value in counts.values():
        _positive_or_zero_int(value, 'count')

    if stock == 0 or affordable == 0:
        return None, 0

    candidate_counts = {choice: counts.get(choice, 0) for choice in choices}

    lowest = min(candidate_counts.values())
    tied = [name for name in choices if candidate_counts[name] == lowest]
    next_count = min((value for value in candidate_counts.values() if value > lowest), default=None)
    available = min(stock, affordable)
    quantity = (available + len(tied) - 1) // len(tied)
    if next_count is not None:
        quantity = min(quantity, next_count - lowest)
    return tied[0], quantity


def confirmed_counts(counts, choice, quantity, unit_price, before, after):
    """Return copied purchase counts after an exactly confirmed currency delta.

    Invalid or ambiguous transaction evidence raises ``ValueError`` and does
    not mutate the caller's mapping.
    """
    if not isinstance(counts, Mapping):
        raise ValueError('counts must be a mapping')
    if not isinstance(choice, str) or choice not in _SELECT_CHOICES:
        raise ValueError('choice is not a valid selection-box option')
    quantity = _positive_or_zero_int(quantity, 'quantity')
    unit_price = _positive_or_zero_int(unit_price, 'unit_price')
    before = _positive_or_zero_int(before, 'before')
    after = _positive_or_zero_int(after, 'after')
    if quantity == 0 or unit_price == 0 or after > before:
        raise ValueError('transaction values must describe a positive purchase')
    if before - after != quantity * unit_price:
        raise ValueError('currency delta does not match the confirmed purchase')

    result = dict(counts.items())
    if any(key not in _SELECT_CHOICES for key in result):
        raise ValueError('counts contains an unknown option')
    for value in result.values():
        _positive_or_zero_int(value, 'count')
    current = _positive_or_zero_int(result.get(choice, 0), 'count')
    result[choice] = current + quantity
    return result
