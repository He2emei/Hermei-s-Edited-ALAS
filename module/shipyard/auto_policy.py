"""Pure limits for CN coin catch-up; counts are shared by rarity, not ship."""
from datetime import timedelta
import re

PR_PRICES = (0, 0, 150, 150, 300, 300, 300, 600, 600, 600, 1050, 1050, 1050, 1050, 1050)
DR_PRICES = (0, 0, 600, 600, 600, 600, 1200, 1200, 1200, 1200, 3000, 3000, 3000, 3000, 3000)


def _integer(value, low=0, high=1000000):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid nonnegative integer')
    return value


def purchase_cost(rarity, purchased, amount):
    _integer(purchased)
    _integer(amount, high=3000)
    if rarity not in ('PR', 'DR'):
        raise ValueError('Unknown blueprint rarity')
    prices = PR_PRICES if rarity == 'PR' else DR_PRICES
    full = 1500 if rarity == 'PR' else 6000
    return sum(prices[i] if i < len(prices) else full for i in range(purchased, purchased + amount))


def infer_purchase_offsets(rarity, observations):
    if not observations:
        raise ValueError('No observed coin preview')
    for amount, cost in observations:
        _integer(amount, 1, 15)
        _integer(cost)
    return tuple(i for i in range(16)
                 if all(purchase_cost(rarity, i, amount) == cost for amount, cost in observations))


def safe_purchase_amount(rarity, possible_offsets, capacity, coins, goal=10):
    if not possible_offsets:
        raise ValueError('Purchase offset is unknown')
    offsets = tuple(_integer(i, 0, 15) for i in possible_offsets)
    _integer(capacity, high=3000)
    _integer(coins)
    _integer(goal, 0, 10)
    limit = min(capacity, max(0, goal - max(offsets)))
    return max(n for n in range(limit + 1)
               if all(purchase_cost(rarity, i, n) <= coins for i in offsets))


def server_day(now):
    return (now - timedelta(hours=4)).date().isoformat()


def parse_required_level(text):
    if not isinstance(text, str):
        return None
    match = re.search(r'需角色到达(\d{1,3})级', re.sub(r'\s+', '', text))
    if match and 1 <= int(match[1]) <= 100:
        return int(match[1])
    return None
