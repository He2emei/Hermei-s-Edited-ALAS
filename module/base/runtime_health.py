"""Main-thread progress marker consumed by the local ALAS guard."""

import json
import os
import re
import time

from module.logger import logger


HEALTH_DIR = os.path.join('log', 'health')
PULSE_INTERVAL = 30
_PROFILE_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_tracker = None


class RuntimeHealth:
    def __init__(self, profile, health_dir=None, clock=None):
        if not isinstance(profile, str) or not _PROFILE_RE.fullmatch(profile):
            raise ValueError('Invalid ALAS profile name')
        self.profile = profile
        self.health_dir = health_dir if health_dir is not None else HEALTH_DIR
        self.clock = clock or time.time
        self.started_at = self.clock()
        self.phase = 'waiting'
        self.task = ''
        self.updated_at = self.started_at
        self._warned_io = False
        self._write()

    def _write(self):
        document = {
            'schema_version': 1,
            'profile': self.profile,
            'pid': os.getpid(),
            'started_at': self.started_at,
            'phase': self.phase,
            'task': self.task,
            'updated_at': self.updated_at,
        }
        temp_path = None
        try:
            os.makedirs(self.health_dir, exist_ok=True)
            path = os.path.join(self.health_dir, f'{self.profile}.json')
            temp_path = f'{path}.{os.getpid()}.tmp'
            with open(temp_path, 'w', encoding='utf-8') as stream:
                json.dump(document, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except OSError as error:
            if not self._warned_io:
                logger.warning(f'Unable to write runtime health for {self.profile}: {error}')
                self._warned_io = True
        finally:
            if temp_path:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    pass

    def _set_state(self, phase, task):
        if self.phase != phase or self.task != task:
            self.phase = phase
            self.task = task
            self.updated_at = self.clock()
            self._write()

    def begin_task(self, task):
        self._set_state('active', str(task))

    def waiting(self):
        self._set_state('waiting', self.task)

    def pulse(self):
        now = self.clock()
        if now - self.updated_at >= PULSE_INTERVAL:
            self.updated_at = now
            self._write()


def start(profile):
    """Start tracking this scheduler process. Called only by ``loop``."""
    global _tracker
    _tracker = RuntimeHealth(profile)


def begin_task(task):
    if _tracker is not None:
        _tracker.begin_task(task)


def waiting():
    if _tracker is not None:
        _tracker.waiting()


def pulse():
    if _tracker is not None:
        _tracker.pulse()


