import os
import re
import subprocess
import sys
from pathlib import Path

from module.logger import logger


DEFAULT_NOTIFY_SCRIPT = (
    Path.home() / '.agents' / 'skills' / 'use-local-infrastructure'
    / 'scripts' / 'napcat_notify.py'
)
PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / '.env'
PREVIEW_ID_PATTERN = re.compile(r'^preview_id:\s*([0-9a-f]{16}|[A-Za-z0-9_-]+)\s*$', re.MULTILINE)
SAFE_LABEL_PATTERN = re.compile(r'[^A-Za-z0-9_.-]+')


def _safe_label(value, fallback):
    value = SAFE_LABEL_PATTERN.sub('_', str(value)).strip('_.-')[:64]
    return value or fallback


def _notification_environment():
    environment = os.environ.copy()
    try:
        lines = PROJECT_ENV_FILE.read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        return environment

    for line in lines:
        key, separator, value = line.partition('=')
        if separator and key.strip() == 'NAPCAT_ACCESS_TOKEN':
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if value:
                environment['NAPCAT_ACCESS_TOKEN'] = value
            break
    return environment


def send_error_notification(
        config_name, task, error, runner=None, timeout=5.0):
    """Send one guarded NapCat error notification without exposing credentials."""
    runner = runner or subprocess.run
    safe_config = _safe_label(config_name, 'UnknownConfig')
    safe_task = _safe_label(task, 'UnknownTask')
    safe_error = _safe_label(type(error).__name__, 'Exception')
    context = f'ALAS/error/{safe_config}/{safe_task}'[:80]
    message = (
        f'ALAS 配置 {safe_config} 的任务 {safe_task} 报错（{safe_error}），'
        f'请查看本机错误日志。'
    )
    command = [
        sys.executable,
        str(DEFAULT_NOTIFY_SCRIPT),
        '--context', context,
        '--message', message,
        '--timeout', str(timeout),
    ]
    run_options = {
        'capture_output': True,
        'text': True,
        'timeout': timeout + 3,
        'check': False,
        'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        'env': _notification_environment(),
    }

    try:
        preview = runner(command, **run_options)
        if preview.returncode != 0:
            logger.warning(f'NapCat error notification preview failed: {preview.stderr.strip()[:300]}')
            return False
        matched = PREVIEW_ID_PATTERN.search(preview.stdout)
        if matched is None:
            logger.warning('NapCat error notification preview did not return a preview_id')
            return False

        send_command = command + [
            '--send',
            '--reason', 'user-request',
            '--preview-id', matched.group(1),
        ]
        sent = runner(send_command, **run_options)
        if sent.returncode != 0:
            logger.warning(f'NapCat error notification failed: {sent.stderr.strip()[:300]}')
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f'NapCat error notification unavailable: {exc}')
        return False
