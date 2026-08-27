class CampaignProfile:
    """Resolve sortie availability without rewriting saved task settings."""

    DAILY = 'daily'
    EVENT = 'event'

    MAIN_SORTIES = frozenset({'Main', 'Main2', 'Main3'})
    EVENT_SORTIES = frozenset({
        'Event', 'Event2',
        'EventA', 'EventB', 'EventC', 'EventD', 'EventSp',
        'Raid', 'RaidDaily', 'Hospital', 'Coalition', 'CoalitionSp',
    })

    def __init__(self, mode):
        self.mode = mode if mode in (self.DAILY, self.EVENT) else self.DAILY

    def allows(self, task):
        if self.mode == self.DAILY:
            return task not in self.EVENT_SORTIES
        return task not in self.MAIN_SORTIES

    def gems_farming_route(self, name, folder, mode):
        if self.mode == self.DAILY and folder != 'campaign_main':
            return '2-4', 'campaign_main', 'normal'
        return name, folder, mode
