import inspect
import unittest
from types import SimpleNamespace
from module.combat.combat import Combat
from module.eventstory.eventstory_base import EventStoryBase

class ScriptedBattleContract(unittest.TestCase):
    def test_inflight_story_battle_uses_execute_then_status_native_signatures(self):
        # The story loop has already observed loading/HUD, so it must not
        # re-enter preparation or send status-only kwargs to combat_execute.
        event = EventStoryBase.__new__(EventStoryBase)
        states = iter(('story', 'finish'))
        event.ui_goto_event_story = lambda: next(states)
        event.event_story = lambda: 'battle'
        event.allow_event_battle_kill_game = False
        expected = lambda: True
        event.combat_expected_end = expected
        seen = []
        def execute(*args, **kwargs):
            inspect.signature(Combat.combat_execute).bind(event, *args, **kwargs)
            seen.append(('execute', args, kwargs))
        def status(*args, **kwargs):
            inspect.signature(Combat.combat_status).bind(event, *args, **kwargs)
            seen.append(('status', args, kwargs))
        event.combat_execute = execute
        event.combat_status = status
        event.combat_preparation = lambda *a, **k: self.fail('inflight battle entered preparation')
        event.app_stop = lambda: self.fail('story battle killed game')
        event.run_event_story()
        self.assertEqual(seen, [('execute', (), {}), ('status', (), {'expected_end': expected})])

if __name__ == '__main__':
    unittest.main()
