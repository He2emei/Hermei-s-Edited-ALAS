from dataclasses import dataclass
from datetime import datetime, timedelta

from module.base.button import Button
from module.ocr.ocr import Digit


COIN_STORAGE_CURRENT = Button(
    area=(735, 22, 785, 52),
    color=(239, 239, 239),
    button=(735, 22, 785, 52),
    file=None,
    name='COIN_STORAGE_CURRENT',
)
COIN_STORAGE_LIMIT = Button(
    area=(736, 0, 780, 22),
    color=(239, 239, 239),
    button=(736, 0, 780, 22),
    file=None,
    name='COIN_STORAGE_LIMIT',
)
MERCHANT_COIN_CURRENT = Button(
    area=(250, 78, 330, 110),
    color=(255, 255, 255),
    button=(250, 78, 330, 110),
    file=None,
    name='MERCHANT_COIN_CURRENT',
)

OCR_COIN_STORAGE_CURRENT = Digit(
    COIN_STORAGE_CURRENT, letter=(239, 239, 239), threshold=128,
    name='OCR_COIN_STORAGE_CURRENT')
OCR_COIN_STORAGE_LIMIT = Digit(
    COIN_STORAGE_LIMIT, letter=(239, 239, 239), threshold=128,
    name='OCR_COIN_STORAGE_LIMIT')
OCR_MERCHANT_COIN_CURRENT = Digit(
    MERCHANT_COIN_CURRENT, letter=(255, 255, 255), threshold=128,
    name='OCR_MERCHANT_COIN_CURRENT')


class CoinResourceReader:
    @staticmethod
    def storage(image):
        return (
            OCR_COIN_STORAGE_CURRENT.ocr(image),
            OCR_COIN_STORAGE_LIMIT.ocr(image),
        )

    @staticmethod
    def merchant(image, available):
        if not available:
            return 0
        return OCR_MERCHANT_COIN_CURRENT.ocr(image)


@dataclass(frozen=True)
class CoinResourceStatus:
    storage_current: int = 0
    storage_limit: int = 0
    merchant_current: int = 0
    merchant_limit: int = 0

    @staticmethod
    def _reached(current, limit, threshold):
        if current < 0 or limit <= 0:
            return False
        threshold = min(max(float(threshold), 0.01), 1.0)
        return current / limit >= threshold

    def warning_reasons(self, storage_threshold, merchant_threshold):
        reasons = []
        if self._reached(self.storage_current, self.storage_limit, storage_threshold):
            reasons.append('storage')
        if self._reached(self.merchant_current, self.merchant_limit, merchant_threshold):
            reasons.append('merchant')
        return tuple(reasons)

    def notification_message(self, config_name, reasons):
        details = []
        if 'storage' in reasons:
            details.append(f'仓库物资 {self.storage_current}/{self.storage_limit}')
        if 'merchant' in reasons:
            details.append(f'小卖部物资 {self.merchant_current}/{self.merchant_limit}')
        joined = '，'.join(details)
        return f'ALAS 配置 {config_name} 的物资接近上限：{joined}。请及时处理。'

    @staticmethod
    def cooldown_elapsed(last_notification, now=None, cooldown_hours=12):
        if last_notification is None or not isinstance(last_notification, datetime):
            return True
        now = now or datetime.now()
        cooldown = timedelta(hours=max(float(cooldown_hours), 0))
        return now - last_notification >= cooldown
