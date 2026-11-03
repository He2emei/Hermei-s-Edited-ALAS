"""Durable receipts for confirmed monthly medal shop transactions."""

import copy
import json
import os
import tempfile
import uuid
from datetime import datetime

from module.shop.medal_monthly_policy import confirmed_counts, priority


_SCHEMA_VERSION = 1
_FAMILIES = {
    'RetrofitT3': frozenset(('dd', 'cl', 'bb', 'cv')),
    'PlateT1': frozenset(('general', 'gun', 'torpedo', 'antiair', 'plane')),
}


def _non_negative_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('{} must be a non-negative integer'.format(label))
    return value


def _month(value):
    if not isinstance(value, str) or len(value) != 7 or value[4] != '-':
        raise ValueError('month must use YYYY-MM')
    try:
        parsed = datetime.strptime(value, '%Y-%m')
    except ValueError:
        raise ValueError('month must use YYYY-MM')
    if parsed.strftime('%Y-%m') != value:
        raise ValueError('month must use YYYY-MM')
    return value


class MedalMonthlyLedger:
    """Persist pending receipts and exact, confirmed monthly purchases."""

    def __init__(self, root, profile, month=None, now=None):
        if profile not in ('alas', 'alas2'):
            raise ValueError('profile must be alas or alas2')
        if month is None:
            month = (now or datetime.now()).strftime('%Y-%m')
        self.profile = profile
        self.month = _month(month)
        self.path = os.path.join(os.fspath(root), 'log', 'shop_medal', '{}-{}.json'.format(profile, self.month))

    def _empty(self):
        return {
            'schema': _SCHEMA_VERSION,
            'profile': self.profile,
            'month': self.month,
            'counts': {'RetrofitT3': {}, 'PlateT1': {}},
            'pending': None,
            'history': [],
        }

    def _validate(self, data):
        if not isinstance(data, dict) or set(data) != {'schema', 'profile', 'month', 'counts', 'pending', 'history'}:
            raise ValueError('invalid ledger structure')
        if type(data['schema']) is not int or data['schema'] != _SCHEMA_VERSION:
            raise ValueError('unsupported ledger schema')
        if data['profile'] != self.profile or data['month'] != self.month:
            raise ValueError('ledger profile or month mismatch')
        families = {'RetrofitT3': frozenset(('dd', 'cl', 'bb', 'cv')),
                    'PlateT1': frozenset(('general', 'gun', 'torpedo', 'antiair', 'plane'))}
        counts = data['counts']
        if not isinstance(counts, dict) or set(counts) != set(families):
            raise ValueError('invalid counts structure')
        for family, choices in families.items():
            values = counts[family]
            if not isinstance(values, dict) or any(key not in choices for key in values):
                raise ValueError('invalid {} counts'.format(family))
            for value in values.values():
                _non_negative_int(value, 'count')
        if not isinstance(data['history'], list):
            raise ValueError('invalid history')
        history_fields = {'txid', 'item_name', 'choice', 'quantity', 'unit_price', 'before', 'family', 'after'}
        for record in data['history']:
            if not isinstance(record, dict) or set(record) != history_fields:
                raise ValueError('invalid history receipt')
            if not isinstance(record['txid'], str) or not record['txid']:
                raise ValueError('invalid history transaction id')
            if not isinstance(record['item_name'], str) or priority(record['item_name']) is None:
                raise ValueError('invalid history item')
            for key in ('quantity', 'unit_price', 'before', 'after'):
                _non_negative_int(record[key], key)
            if record['quantity'] == 0 or record['unit_price'] == 0:
                raise ValueError('invalid history purchase')
            if record['after'] > record['before'] or record['before'] - record['after'] != record['quantity'] * record['unit_price']:
                raise ValueError('invalid history balance delta')
            family = record['family']
            if family is None:
                if record['choice'] is not None:
                    raise ValueError('ordinary history item cannot have a selection choice')
            elif not isinstance(family, str) or family not in families or not isinstance(record['choice'], str) or record['choice'] not in families[family]:
                raise ValueError('invalid history family/choice')
        pending = data['pending']
        if pending is not None:
            required = {'txid', 'item_name', 'choice', 'quantity', 'unit_price', 'before', 'family'}
            if not isinstance(pending, dict) or set(pending) != required:
                raise ValueError('invalid pending receipt')
            if not isinstance(pending['txid'], str) or not pending['txid']:
                raise ValueError('invalid pending transaction id')
            if not isinstance(pending['item_name'], str) or priority(pending['item_name']) is None:
                raise ValueError('invalid pending item')
            for key in ('quantity', 'unit_price', 'before'):
                _non_negative_int(pending[key], key)
            if pending['quantity'] == 0 or pending['unit_price'] == 0:
                raise ValueError('invalid pending purchase')
            if pending['quantity'] * pending['unit_price'] > pending['before']:
                raise ValueError('pending purchase exceeds recorded balance')
            family = pending['family']
            if family is not None and (not isinstance(family, str) or family not in families or not isinstance(pending['choice'], str) or pending['choice'] not in families[family]):
                raise ValueError('invalid pending family/choice')
            if family is None and pending['choice'] is not None:
                raise ValueError('ordinary item cannot have a selection choice')
        return data

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return copy.deepcopy(self._empty())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('ledger JSON is corrupt') from exc
        return copy.deepcopy(self._validate(data))

    def _write(self, data):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix='.medal-ledger-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def prepare(self, item_name, choice, quantity, unit_price, before, family=None):
        data = self.load()
        if data['pending'] is not None:
            raise ValueError('a transaction is already pending')
        if not isinstance(item_name, str) or priority(item_name) is None:
            raise ValueError('item is unknown or protected')
        quantity = _non_negative_int(quantity, 'quantity')
        unit_price = _non_negative_int(unit_price, 'unit_price')
        before = _non_negative_int(before, 'before')
        if quantity == 0 or unit_price == 0 or before <= 0 or quantity * unit_price > before:
            raise ValueError('invalid purchase quantity, price, or balance')
        families = {'RetrofitT3': frozenset(('dd', 'cl', 'bb', 'cv')),
                    'PlateT1': frozenset(('general', 'gun', 'torpedo', 'antiair', 'plane'))}
        if family is None:
            if choice is not None:
                raise ValueError('choice requires a selection-box family')
        elif not isinstance(family, str) or family not in families or not isinstance(choice, str) or choice not in families[family]:
            raise ValueError('choice does not belong to family')
        receipt = {
            'txid': uuid.uuid4().hex,
            'item_name': item_name,
            'choice': choice,
            'quantity': quantity,
            'unit_price': unit_price,
            'before': before,
            'family': family,
        }
        data['pending'] = receipt
        self._write(data)
        return copy.deepcopy(receipt)

    def commit(self, txid, after):
        data = self.load()
        pending = data['pending']
        if pending is None or not isinstance(txid, str) or pending['txid'] != txid:
            raise ValueError('transaction id does not match pending receipt')
        after = _non_negative_int(after, 'after')
        if after > pending['before']:
            raise ValueError('balance increased during purchase')
        delta_matches = pending['before'] - after == pending['quantity'] * pending['unit_price']
        if not delta_matches:
            raise ValueError('currency delta does not match the confirmed purchase')
        if pending['family'] is not None:
            family = pending['family']
            data['counts'][family] = confirmed_counts(
                data['counts'][family], pending['choice'], pending['quantity'],
                pending['unit_price'], pending['before'], after)
        data['history'].append(dict(pending, after=after))
        data['pending'] = None
        self._write(data)
        return copy.deepcopy(data)
