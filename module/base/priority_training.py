"""Exact, ordered ship names configured for focused OpSi training."""

import re


def priority_ship_names(config):
    value = getattr(config, 'PriorityTraining_Ships', '')
    if not isinstance(value, str):
        raise ValueError('PriorityTraining_Ships must be text')
    return tuple(dict.fromkeys(name.strip() for name in re.split(r'[>\r\n,，]+', value)
                               if name.strip()))


def allow_priority_125(config, name):
    return (name in priority_ship_names(config)
            and getattr(config, 'PriorityTraining_Allow125Awakening', False) is True)
