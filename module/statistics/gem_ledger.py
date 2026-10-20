"""Passive local history of observed CN gem balances."""
import csv
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

from module.logger import logger
from module.ocr.ocr import Ocr


GEM_BALANCE_AREA = (864, 22, 954, 50)
CHINA_TZ = timezone(timedelta(hours=8))
PROFILE_RE = re.compile(r'^[A-Za-z0-9_-]+$')
BALANCE_RE = re.compile(r'^\d+$')
GEM_BALANCE_OCR = Ocr(
    [GEM_BALANCE_AREA], alphabet='0123456789', letter=(255, 243, 82),
    threshold=128, name='GEM_BALANCE')
CSV_FIELDS = [
    'date', 'first', 'last', 'min', 'max', 'samples', 'net_change',
    'previous_date', 'gap_days',
]


def _china_time(value=None):
    value = value or datetime.now(CHINA_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=CHINA_TZ)
    return value.astimezone(CHINA_TZ)


def _paths(profile, data_dir):
    if not isinstance(profile, str) or not PROFILE_RE.match(profile):
        raise ValueError('Invalid profile name')
    directory = os.path.abspath(data_dir or os.path.join('log', 'resource_ledger'))
    return directory, os.path.join(directory, profile + '-gems.sqlite3'), \
        os.path.join(directory, profile + '-gems-daily.csv')


def _atomic_csv(path, rows):
    fd, temporary = tempfile.mkstemp(prefix='.gems-', suffix='.csv', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _export(connection, path):
    grouped = connection.execute(
        'SELECT observed_at, balance FROM observations ORDER BY observed_at, id').fetchall()
    by_day = {}
    for observed_at, balance in grouped:
        # SQLite date() normalizes offsets to UTC. Keep the recorded China
        # calendar date by using the date prefix of the persisted ISO value.
        day = observed_at[:10]
        by_day.setdefault(day, []).append((int(balance), observed_at))
    rows = []
    previous_date = None
    previous_last = None
    for day in sorted(by_day):
        balances = [value for value, _ in by_day[day]]
        gap = (datetime.strptime(day, '%Y-%m-%d').date() -
               datetime.strptime(previous_date, '%Y-%m-%d').date()).days if previous_date else None
        rows.append({
            'date': day,
            'first': balances[0],
            'last': balances[-1],
            'min': min(balances),
            'max': max(balances),
            'samples': len(balances),
            'net_change': balances[-1] - previous_last if previous_date else '',
            'previous_date': previous_date or '',
            'gap_days': gap if previous_date else '',
        })
        previous_date, previous_last = day, balances[-1]
    _atomic_csv(path, rows)


def record_balance(profile, balance, observed_at=None, source='reward_home', evidence='', data_dir=None):
    """Store one validated observed inventory balance and refresh daily CSV."""
    if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
        return False
    timestamp = _china_time(observed_at).isoformat(timespec='seconds')
    directory, database, csv_path = _paths(profile, data_dir)
    os.makedirs(directory, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            balance INTEGER NOT NULL CHECK(balance >= 0),
            source TEXT NOT NULL,
            evidence TEXT NOT NULL,
            UNIQUE(observed_at, source)
        )''')
        with connection:
            connection.execute(
                'INSERT OR IGNORE INTO observations(observed_at,balance,source,evidence) VALUES(?,?,?,?)',
                (timestamp, balance, str(source), str(evidence)))
            inserted = connection.total_changes > 0
        # SQLite is authoritative. Publish the derived CSV only after commit;
        # on export failure, preserve the observation and retry on the next call.
        try:
            _export(connection, csv_path)
        except Exception as exc:
            logger.warning(f'Unable to export gem balance ledger: {exc}')
        return inserted
    finally:
        connection.close()


def _ocr_balance(image):
    try:
        shape = getattr(image, 'shape', None)
        if shape is None or len(shape) < 2 or shape[0] != 720 or shape[1] != 1280:
            return None
        raw = GEM_BALANCE_OCR.ocr(image)
        if not isinstance(raw, str):
            return None
        raw = raw.strip()
        return int(raw) if BALANCE_RE.match(raw) else None
    except Exception as exc:
        logger.warning(f'Unable to recognize gem balance: {exc}')
        return None


def record_home_frames(profile, images, observed_at=None, source='reward_home', evidence='', data_dir=None):
    """Record when at least two valid frame reads agree; failures are ignored."""
    if not isinstance(images, (list, tuple)):
        return False
    readings = [_ocr_balance(image) for image in images]
    valid = [value for value in readings if value is not None]
    counts = Counter(valid)
    accepted = [value for value, count in counts.items() if count >= 2]
    if not accepted:
        return False
    try:
        return record_balance(profile, accepted[0], observed_at, source, evidence, data_dir)
    except Exception as exc:
        logger.warning(f'Unable to record gem balance: {exc}')
        return False
