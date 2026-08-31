from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from module.base.button import Button
from module.ocr.ocr import Digit


COIN_STORAGE_CURRENT = Button(
    area=(716, 24, 780, 49),
    color=(239, 239, 239),
    button=(716, 24, 780, 49),
    file=None,
    name='COIN_STORAGE_CURRENT',
)
COIN_STORAGE_LIMIT = Button(
    area=(716, 0, 780, 22),
    color=(239, 239, 239),
    button=(716, 0, 780, 22),
    file=None,
    name='COIN_STORAGE_LIMIT',
)
OCR_COIN_STORAGE_CURRENT = Digit(
    COIN_STORAGE_CURRENT, letter=(239, 239, 239), threshold=128,
    name='OCR_COIN_STORAGE_CURRENT')
OCR_COIN_STORAGE_LIMIT = Digit(
    COIN_STORAGE_LIMIT, letter=(239, 239, 239), threshold=128,
    name='OCR_COIN_STORAGE_LIMIT')
def read_coin_storage(image):
    return (
        OCR_COIN_STORAGE_CURRENT.ocr(image),
        OCR_COIN_STORAGE_LIMIT.ocr(image),
    )

@dataclass(frozen=True)
class CoinResourceStatus:
    storage_current: int = 0
    storage_limit: int = 0

    @staticmethod
    def storage_limit_valid(limit):
        # A four-digit result is a known clipped read of the five-digit
        # warehouse limit (for example 9200 instead of 94200).
        return isinstance(limit, int) and limit >= 10000

    @classmethod
    def from_readings(cls, readings):
        valid = [
            (current, limit)
            for current, limit in readings
            if current >= 0 and cls.storage_limit_valid(limit)
        ]
        if not valid:
            return cls()
        return cls(
            storage_current=int(median(current for current, _ in valid)),
            storage_limit=int(median(limit for _, limit in valid)),
        )

    @staticmethod
    def _reached(current, limit, threshold):
        if current < 0 or not CoinResourceStatus.storage_limit_valid(limit):
            return False
        threshold = min(max(float(threshold), 0.01), 1.0)
        return current / limit >= threshold

    def storage_warning_reached(self, storage_threshold):
        return self._reached(
            self.storage_current,
            self.storage_limit,
            storage_threshold,
        )

    def notification_message(self, config_name):
        return (
            f'ALAS 配置 {config_name} 的仓库物资已达到预警阈值：'
            f'{self.storage_current}/{self.storage_limit}。请及时处理。'
        )

    @staticmethod
    def cooldown_elapsed(last_notification, now=None, cooldown_hours=12):
        if last_notification is None or not isinstance(last_notification, datetime):
            return True
        now = now or datetime.now()
        cooldown = timedelta(hours=max(float(cooldown_hours), 0))
        return now - last_notification >= cooldown
