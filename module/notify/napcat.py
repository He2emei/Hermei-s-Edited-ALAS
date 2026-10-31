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
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r'(?i)(NAPCAT_ACCESS_TOKEN\s*[=:]\s*)[^\s,;]+'),
    re.compile(r'(?i)(\b(?:access[_ -]?token|api[_ -]?token|token)\s*[=:]\s*)[^\s,;]+'),
    re.compile(r'(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*'),
)
FAILURE_LINE_PATTERN = re.compile(
    r'(?i)(?:\berror\b|\bexception\b|\bfailed\b|\bfailure\b|'
    r'\bdenied\b|\bunauthorized\b|\binvalid\b|\btimeout\b)')
# Leave room for the fixed logger prefix so the complete warning stays bounded.
FAILURE_DETAIL_LIMIT = 260


def _safe_label(value, fallback):
    value = SAFE_LABEL_PATTERN.sub('_', str(value)).strip('_.-')[:64]
    return value or fallback


def _redact_sensitive_values(value):
    value = str(value)
    for pattern in SENSITIVE_VALUE_PATTERNS:
        value = pattern.sub(lambda match: f'{match.group(1)}[REDACTED]', value)
    return value


def _failure_detail(stderr):
    """Keep the actionable stderr tail while avoiding usage-only diagnostics."""
    lines = [line.strip() for line in str(stderr or '').splitlines() if line.strip()]
    if not lines:
        return 'no stderr output'

    # argparse prints its full usage before the short, actionable parser.error line.
    error_lines = [line for line in lines if FAILURE_LINE_PATTERN.search(line)]
    detail = error_lines[-1] if error_lines else '\n'.join(lines[-3:])
    detail = _redact_sensitive_values(detail)
    if len(detail) > FAILURE_DETAIL_LIMIT:
        detail = detail[-FAILURE_DETAIL_LIMIT:]
    return detail


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


def send_notification(context, message, runner=None, timeout=5.0):
    """Send one guarded NapCat notification without exposing credentials."""
    runner = runner or subprocess.run
    context = str(context).strip()[:80]
    message = str(message).strip()[:1000]
    if not context or not message:
        logger.warning('NapCat notification requires non-empty context and message')
        return False
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
            logger.warning(
                f'NapCat notification preview failed: '
                f'{_failure_detail(preview.stderr)}')
            return False
        matched = PREVIEW_ID_PATTERN.search(preview.stdout)
        if matched is None:
            logger.warning('NapCat notification preview did not return a preview_id')
            return False

        send_command = command + [
            '--send',
            '--reason', 'user-request',
            '--preview-id', matched.group(1),
        ]
        sent = runner(send_command, **run_options)
        if sent.returncode != 0:
            logger.warning(
                f'NapCat notification failed: {_failure_detail(sent.stderr)}')
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            f'NapCat notification unavailable: '
            f'{_failure_detail(str(exc))}')
        return False


def send_error_notification(
        config_name, task, error, runner=None, timeout=5.0):
    """Send one guarded NapCat error notification without exposing credentials."""
    safe_config = _safe_label(config_name, 'UnknownConfig')
    safe_task = _safe_label(task, 'UnknownTask')
    safe_error = _safe_label(type(error).__name__, 'Exception')
    context = f'ALAS/error/{safe_config}/{safe_task}'
    message = (
        f'ALAS 配置 {safe_config} 的任务 {safe_task} 报错（{safe_error}），'
        f'请查看本机错误日志。'
    )
    return send_notification(
        context=context,
        message=message,
        runner=runner,
        timeout=timeout,
    )
