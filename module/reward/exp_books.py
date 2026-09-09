from datetime import datetime

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.notify.napcat import send_notification


EXP_BOOK_KEY = 'exp_book_t1'
DEFAULT_THRESHOLD = 2900
DEFAULT_TIME = datetime(2020, 1, 1)


def _valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_exp_book_warning(config, device, now=None):
    """Read and warn about T1 books at most once per local day."""
    if not getattr(config, 'ExpBookWarning_Enable', False):
        return False

    now = now or datetime.now().replace(microsecond=0)
    last_check = getattr(config, 'ExpBookWarning_LastCheck', DEFAULT_TIME)
    count = getattr(config, 'ExpBookWarning_LastCount', -1)
    checked_today = isinstance(last_check, datetime) and last_check.date() == now.date()

    if not checked_today:
        try:
            from module.storage.training_inventory import TrainingInventory
            readings = TrainingInventory(config, device).read_counts([EXP_BOOK_KEY])
            count = readings.get(EXP_BOOK_KEY)
            if not _valid_count(count):
                raise RequestHumanTakeover('Invalid experience book inventory')
        except Exception as exc:
            logger.warning(f'Unable to read experience book inventory: {exc}')
            return False
        config.ExpBookWarning_LastCheck = now
        config.ExpBookWarning_LastCount = count
        logger.info(f'Experience book inventory: {count}')
    elif not _valid_count(count):
        logger.warning('Cached experience book inventory is unknown')
        return False

    threshold = getattr(config, 'ExpBookWarning_Threshold', DEFAULT_THRESHOLD)
    if not _valid_count(threshold) or count <= threshold:
        return False
    last_notification = getattr(config, 'ExpBookWarning_LastNotification', DEFAULT_TIME)
    if isinstance(last_notification, datetime) and last_notification.date() == now.date():
        logger.info('Experience book warning already sent today')
        return False

    config_name = getattr(config, 'config_name', 'UnknownConfig')
    sent = send_notification(
        context=f'ALAS/resource/{config_name}/exp-book'[:80],
        message=f'ALAS 配置 {config_name} 的普通经验书库存为 {count}，已超过阈值 {threshold}。',
    )
    if sent:
        config.ExpBookWarning_LastNotification = now
        logger.warning(f'Experience book warning sent: {count} > {threshold}')
    else:
        logger.warning('Experience book warning notification failed; will retry')
    return sent
