import re
from typing import List
from module.config.config_generated import GeneratedConfig
from module.os_shop.preset import *
from module.os_shop.item import OSShopItem as Item
from module.base.filter import Filter

FILTER_REGEX = re.compile(
    '^(actionpoint|crystallizedheatresistantsteel|developmentmaterial'
    '|energystoragedevice|geardesignplan|gearpart|logger|metaredbook'
    '|nanoceramicalloy|neuroplasticprostheticarm|ordnancetestingreport'
    '|platerandom|purplecoins|repairpack|supercavitationgenerator|tuningsample'
    '|tuning)'

    '(20|50|100|prototype|specialized|abyssal|obscure|full2|full|triple2|triple|2'
    '|combat|offence|survival)?'

    '(t[1-6])?$',
    flags=re.IGNORECASE)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)

PORT_NEW_YORK = 0
PORT_LIVERPOOL = 1
PORT_GIBRALTAR = 2
PORT_ST_PETERSBURG = 3

ITEM_GROUP_LOGGER = 'logger'
ITEM_GROUP_PURPLE_COINS = 'purplecoins'
ITEM_GROUP_REPAIR_PACK = 'repairpack'


class Selector():

    MONTHLY_CLEAROUT_PORT_FILTERS = {
        # New York: coordinates only.
        PORT_NEW_YORK: lambda item: item.group == ITEM_GROUP_LOGGER,
        # Liverpool: everything except special exchange tokens.
        PORT_LIVERPOOL: lambda item: item.group != ITEM_GROUP_PURPLE_COINS,
        # Gibraltar: clear the entire shop.
        PORT_GIBRALTAR: lambda item: True,
        # St. Petersburg: everything except repair packs.
        PORT_ST_PETERSBURG: lambda item: item.group != ITEM_GROUP_REPAIR_PACK,
    }

    def pretreatment(self, items) -> List[Item]:
        """
        Pretreatment items.

        Args:
            items:

        Returns:
            list[Item]:
        """
        _items = []
        for item in items:
            item.group, item.sub_genre, item.tier = None, None, None
            result = re.search(FILTER_REGEX, item.name.lower())
            if result:
                item.group, item.sub_genre, item.tier = [group.lower()
                                                         if group is not None else None
                                                         for group in result.groups()]
                _items.append(item)

        return _items

    def enough_coins_in_akashi(self, item) -> bool:
        """
        Check if there are enough coins to buy the item.

        Args:
            item:

        Returns:
            bool: True if there are enough coins.
        """
        if item.cost == 'YellowCoins' and item.price <= self._shop_yellow_coins:
            return True
        if item.cost == 'PurpleCoins' and item.price <= self._shop_purple_coins:
            return True

        return False

    def check_cl1_purple_coins(self, item) -> bool:
        """
        Check if cl1 is enable and item name is PurpleCoins.

        Args:
            item:

        Returns:
            bool: False if cl1 is enable and item name is PurpleCoins.
        """
        return not (self.is_cl1_enabled and item.name == 'PurpleCoins')

    def check_item_count(self, item) -> bool:
        """
        Check if the item has a valid count.
        
        Args:
            item: Irem.
            
        Returns:
            bool: True if the item has at least one count, the total count is at least one,
                  and the current count does not exceed the total count. False otherwise.
        """
        return item.count >= 1 and item.total_count >= 1 and item.count <= item.total_count

    def items_filter_in_akashi_shop(self, items) -> List[Item]:
        """
        Returns items that can be bought.

        Args:
            items: Irems to be filtered.

        Returns:
            list[Item]:
        """
        items = self.pretreatment(items)
        parser = self.config.OpsiGeneral_AkashiShopFilter
        if not parser.strip():
            parser = GeneratedConfig.OpsiGeneral_AkashiShopFilter
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.enough_coins_in_akashi])

    def items_filter_in_os_shop(self, items) -> List[Item]:
        """
        Returns items that can be bought.

        Args:
            items: Items to be filtered.

        Returns:
            list[Item]:
        """
        items = self.pretreatment(items)
        preset = self.config.OpsiShop_PresetFilter
        parser = ''
        if preset == 'custom':
            parser = self.config.OpsiShop_CustomFilter
            if not parser.strip():
                parser = OS_SHOP[GeneratedConfig.OpsiShop_PresetFilter]
        else:
            parser = OS_SHOP[preset]
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.check_item_count])

    def items_filter_in_monthly_clearout(self, items) -> List[Item]:
        """
        Select items for the end-of-month clearout using a fixed rule per port.

        Unknown items and invalid counters are skipped defensively. Port indices
        are assigned by :meth:`PortShop.scan_all` in the order shown by the game:
        New York, Liverpool, Gibraltar, and St. Petersburg.

        Args:
            items: Items scanned from all four port shops.

        Returns:
            list[Item]: Items targeted by the monthly clearout.
        """
        selected = []
        for item in self.pretreatment(items):
            if not self.check_item_count(item):
                continue
            port_filter = self.MONTHLY_CLEAROUT_PORT_FILTERS.get(item.shop_index)
            if port_filter is not None and port_filter(item):
                selected.append(item)
        return selected
