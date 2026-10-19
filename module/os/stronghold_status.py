import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta

from module.logger import logger

STATUS_DIR = os.path.join('log', 'opsi_stronghold')
HISTORY_LIMIT = 50
SCHEMA_VERSION = 1


def _safe_profile(profile):
    profile = str(profile or '')
    if not re.match(r'^[A-Za-z0-9_-]{1,64}$', profile):
        raise ValueError('Unsafe profile name')
    return profile


def _utc_now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def _game_month(timestamp=None):
    # Game month follows China Standard Time (UTC+8), independent of host timezone.
    utc = datetime.utcnow() if timestamp is None else datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
    return (utc + timedelta(hours=8)).strftime('%Y-%m')


def _path(profile):
    return os.path.join(STATUS_DIR, _safe_profile(profile) + '.json')


def _empty(profile):
    return {'schema_version': SCHEMA_VERSION, 'profile': profile, 'attempt': None, 'history': [], 'last_check': None}


def _read(profile):
    try:
        profile = _safe_profile(profile)
        with open(_path(profile), 'r', encoding='utf-8') as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get('profile') != profile:
            raise ValueError('invalid status document/profile')
        history = data.get('history', [])
        if not isinstance(history, list):
            logger.warning('Invalid stronghold history; recovering with an empty history')
            history = []
        else:
            valid_history = [item for item in history if isinstance(item, dict) and item.get('attempt_id')]
            if len(valid_history) != len(history):
                logger.warning('Malformed stronghold history entries ignored')
            history = valid_history[-HISTORY_LIMIT:]
        if data.get('schema_version') != SCHEMA_VERSION:
            logger.warning('Stronghold status schema upgraded to version %s' % SCHEMA_VERSION)
        data['schema_version'] = SCHEMA_VERSION
        data['history'] = history
        data.setdefault('attempt', None)
        data.setdefault('last_check', None)
        if data['last_check'] is not None and not isinstance(data['last_check'], dict):
            logger.warning('Malformed last stronghold check ignored')
            data['last_check'] = None
        if data['attempt'] is not None and not isinstance(data['attempt'], dict):
            logger.warning('Malformed current stronghold attempt ignored')
            data['attempt'] = None
        return data
    except FileNotFoundError:
        try:
            return _empty(_safe_profile(profile))
        except Exception as error:
            logger.warning('Unable to read stronghold status: %s' % error)
            return _empty('unknown')
    except Exception as error:
        logger.warning('Unable to read stronghold status; recovering safely: %s' % error)
        try:
            return _empty(_safe_profile(profile))
        except Exception:
            return _empty('unknown')


def _write(profile, data):
    temp_path = None
    try:
        profile = _safe_profile(profile)
        path = _path(profile)
        directory = os.path.dirname(path)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        fd, temp_path = tempfile.mkstemp(prefix='.' + profile + '-', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except Exception as error:
        logger.warning('Unable to persist stronghold status: %s' % error)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False
    return True


def _update_history(history, attempt):
    for index in range(len(history) - 1, -1, -1):
        if history[index].get('attempt_id') == attempt.get('attempt_id'):
            history[index] = attempt.copy()
            break
    else:
        history.append(attempt.copy())
    return history[-HISTORY_LIMIT:]


def check(profile, found, zone=None):
    try:
        profile = _safe_profile(profile)
        data = _read(profile)
        now = _utc_now()
        data['profile'] = profile
        data['last_check'] = {
            'time_utc': now, 'game_month': _game_month(now), 'stronghold_found': bool(found),
            'zone_id': getattr(zone, 'zone_id', None) if found else None,
            'zone_name': getattr(zone, 'cn', None) if found else None,
        }
        return _write(profile, data)
    except Exception as error:
        logger.warning('Unable to record stronghold check: %s' % error)
        return False


def begin(profile, zone):
    now = _utc_now()
    attempt = {
        'attempt_id': str(uuid.uuid4()), 'time_utc': now, 'game_month': _game_month(now),
        'zone_id': getattr(zone, 'zone_id', None), 'zone_name': getattr(zone, 'cn', None),
        'status': 'running', 'fleets': [], 'remaining_percentage': None,
        'progress_basis': None,
    }
    try:
        profile = _safe_profile(profile)
        data = _read(profile)
        data['profile'] = profile
        data['attempt'] = attempt
        data['last_check'] = {
            'time_utc': now, 'game_month': attempt['game_month'], 'stronghold_found': True,
            'zone_id': attempt['zone_id'], 'zone_name': attempt['zone_name'],
        }
        data['history'] = _update_history(data.setdefault('history', []), attempt)
        _write(profile, data)
    except Exception as error:
        logger.warning('Unable to begin stronghold status record: %s' % error)
    return attempt


def fleet_progress(profile, attempt, fleet, percentage):
    try:
        fleet_name = str(getattr(fleet, 'fleet_index', fleet))
        if fleet_name not in attempt['fleets']:
            attempt['fleets'].append(fleet_name)
        attempt['remaining_percentage'] = percentage
        attempt['progress_basis'] = 'native_stronghold_percentage_ocr'
        profile = _safe_profile(profile)
        data = _read(profile)
        data['profile'] = profile
        data['attempt'] = attempt
        data['history'] = _update_history(data.setdefault('history', []), attempt)
        _write(profile, data)
    except Exception as error:
        logger.warning('Unable to record stronghold progress: %s' % error)


def finish(profile, attempt, status):
    try:
        profile = _safe_profile(profile)
        attempt['status'] = status
        attempt['finished_time_utc'] = _utc_now()
        data = _read(profile)
        data['profile'] = profile
        data['attempt'] = attempt
        data['history'] = _update_history(data.setdefault('history', []), attempt)
        persisted = _write(profile, data)
        logger.info('Stronghold outcome: profile=%s zone=%s status=%s remaining=%s persisted=%s' % (
            profile, attempt.get('zone_id'), status, attempt.get('remaining_percentage'), persisted))
        return persisted
    except Exception as error:
        logger.warning('Unable to finish stronghold status record: %s' % error)
        return False
