import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.combat.combat import Combat
from module.eventstory.eventstory_base import EventStoryBase


class ScriptedBattleContract(unittest.TestCase):
    def make_combat(self):
        combat = Combat.__new__(Combat)
        combat.device = SimpleNamespace(image=object(), click=Mock())
        combat.device.screenshot = Mock(side_effect=lambda: setattr(combat.device, 'image', object()))
        combat.device.stuck_record_clear = Mock()
        combat.device.click_record_clear = Mock()
        combat.submarine_call_reset = Mock()
        combat.combat_auto_reset = Mock()
        combat.combat_manual_reset = Mock()
        for name in ('handle_combat_automation_confirm', 'handle_story_skip',
                     'handle_combat_auto', 'handle_combat_manual',
                     'handle_combat_weapon_release', 'handle_submarine_call',
                     'handle_popup_confirm', 'handle_urgent_commission',
                     'handle_guild_popup_cancel', 'handle_vote_popup',
                     'handle_mission_popup_ack', 'handle_battle_status',
                     'handle_get_items'):
            setattr(combat, name, Mock(return_value=False))
        return combat

    def test_event_story_passes_the_same_end_callback_to_native_execute_and_status(self):
        # The story loop has already observed loading/HUD; it must not
        # re-enter preparation; both phases receive the same end predicate.
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
        self.assertEqual(seen, [
            ('execute', (), {'expected_end': expected}),
            ('status', (), {'expected_end': expected}),
        ])
        self.assertIs(seen[0][2]['expected_end'], seen[1][2]['expected_end'])

    def test_native_execute_exits_on_fresh_confirmed_end_before_combat_handlers(self):
        combat = self.make_combat()
        initial_image = combat.device.image
        observed_screenshots = []

        def expected_end():
            observed_screenshots.append((combat.device.screenshot.call_count,
                                         combat.device.image is not initial_image))
            return True

        Combat.combat_execute(combat, expected_end=expected_end)
        self.assertEqual(observed_screenshots, [(1, True)])
        combat.device.screenshot.assert_called_once_with()
        combat.handle_combat_automation_confirm.assert_not_called()
        combat.handle_story_skip.assert_not_called()
        combat.handle_combat_auto.assert_not_called()
        combat.handle_battle_status.assert_not_called()
        combat.handle_get_items.assert_not_called()
        combat.device.click_record_clear.assert_called_once_with()
        combat.device.click.assert_not_called()

    def test_invalid_end_callback_rejected_before_device_or_combat_reset(self):
        combat = self.make_combat()
        with self.assertRaisesRegex(TypeError, 'expected_end must be callable or None'):
            Combat.combat_execute(combat, expected_end=True)
        combat.submarine_call_reset.assert_not_called()
        combat.combat_auto_reset.assert_not_called()
        combat.combat_manual_reset.assert_not_called()
        combat.device.stuck_record_clear.assert_not_called()
        combat.device.click_record_clear.assert_not_called()
        combat.device.screenshot.assert_not_called()

    def test_none_keeps_legacy_loop_and_old_positional_signature_binding(self):
        combat = self.make_combat()
        combat.handle_battle_status.return_value = True
        Combat.combat_execute(combat)
        combat.device.screenshot.assert_not_called()
        combat.handle_battle_status.assert_called_once()
        combat.handle_get_items.assert_not_called()
        signature = inspect.signature(Combat.combat_execute)
        signature.bind(combat)
        signature.bind(combat, 'combat_manual', 'do_not_use', None)
        signature.bind(combat, expected_end=None)
        with self.assertRaises(TypeError):
            signature.bind(combat, unsupported=True)


if __name__ == '__main__':
    unittest.main()
