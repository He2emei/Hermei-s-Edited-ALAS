"""Emit a bounded account-care event when the home coin store is full."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from module.logger import logger


EVENT_NAMESPACE = uuid.UUID('5c82d77d-04bb-4cce-870c-3210df897bb6')
CARE_TASK = 'ALAS-Resource-Care'
MIN_STORAGE_LIMIT = 10000


def _utc_datetime(value):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid_reading(reading):
    if not isinstance(reading, (tuple, list)) or len(reading) != 2:
        return None
    current, limit = reading
    if (isinstance(current, bool) or not isinstance(current, int) or current < 0 or
            isinstance(limit, bool) or not isinstance(limit, int) or
            limit < MIN_STORAGE_LIMIT or current < limit):
        return None
    return current, limit


def _launch_care_task(launcher):
    if sys.platform != 'win32':
        return
    launcher = launcher or subprocess.run
    result = launcher(
        ['schtasks.exe', '/Run', '/TN', CARE_TASK],
        capture_output=True,
        timeout=3,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if getattr(result, 'returncode', 0) != 0:
        raise RuntimeError('Resource care task launcher returned a failure code')


def emit_coin_care_event(profile, status, readings, *, root=Path('log/resource_care'),
                         now=None, cooldown_hours=12, launcher=None):
    """Write one idempotent full-coin event and best-effort start its consumer.

    The warehouse limit is a soft threshold; events require two matching raw
    readings at or above that limit. No game state or resources are changed.
    """
    created_path = None
    try:
        if profile not in ('alas', 'alas2'):
            return None

        current_status = getattr(status, 'storage_current', None)
        limit_status = getattr(status, 'storage_limit', None)
        if (isinstance(current_status, bool) or not isinstance(current_status, int) or
                isinstance(limit_status, bool) or not isinstance(limit_status, int)):
            return None

        valid = [_valid_reading(reading) for reading in readings or ()]
        valid = [reading for reading in valid if reading is not None]
        consensus = (current_status, limit_status)
        matching = [reading for reading in valid if reading == consensus]
        if len(matching) < 2:
            return None
        current, limit = consensus

        now_utc = _utc_datetime(now)
        try:
            window_hours = max(12, int(cooldown_hours))
        except (TypeError, ValueError, OverflowError):
            window_hours = 12
        window_seconds = window_hours * 60 * 60
        window = int(now_utc.timestamp()) // window_seconds
        event_id = str(uuid.uuid5(EVENT_NAMESPACE, f'coin_overflow/{profile}/{window}'))
        event = {
            'schema': 1,
            'event_id': event_id,
            'kind': 'coin_overflow',
            'profile': profile,
            'observed_at_utc': now_utc.isoformat().replace('+00:00', 'Z'),
            'coins_current': current,
            'coins_limit': limit,
            'readings': [list(reading) for reading in matching],
            'worker_pid': os.getpid(),
        }

        event_dir = Path(root) / 'events'
        event_dir.mkdir(parents=True, exist_ok=True)
        created_path = event_dir / f'{event_id}.json'
        with created_path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(event, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return None
    except Exception as exc:
        # A visible file may already have been observed by the native queue
        # scanner. Retain any partial artifact for diagnosis, never erase it
        # or silently retry the same event as a new transaction.
        logger.warning(f'Unable to emit coin care event: {type(exc).__name__}')
        return None

    try:
        _launch_care_task(launcher)
    except Exception as exc:
        logger.warning(f'Unable to start resource care task: {type(exc).__name__}')
    return created_path
