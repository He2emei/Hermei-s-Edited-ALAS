import unittest

from module.os_handler.action_point import ActionPointHandler
from module.os_handler.assets import IN_MAP
from module.ui.assets import OS_CHECK


class GlobeReturnHarness:
    def __init__(self):
        self._action_point_total = 4675
        self.appear_calls = []

    def action_point_enter(self):
        pass

    def action_point_safe_get(self):
        pass

    def action_point_quit(self):
        pass

    def handle_action_point(self, *args, **kwargs):
        return True

    def loop(self):
        yield None
        raise AssertionError('action_point_check kept waiting after returning to the OpSi globe')

    def appear(self, button, **kwargs):
        self.appear_calls.append(button)
        return button is OS_CHECK


class ActionPointReturnStateTest(unittest.TestCase):
    def test_check_accepts_opsi_globe_after_closing_popup(self):
        handler = GlobeReturnHarness()

        enough = ActionPointHandler.action_point_check(handler, 1000)

        self.assertTrue(enough)
        self.assertEqual(handler.appear_calls, [IN_MAP, OS_CHECK])

    def test_set_accepts_opsi_globe_after_closing_popup(self):
        handler = GlobeReturnHarness()

        handled = ActionPointHandler.action_point_set(handler, cost=0)

        self.assertTrue(handled)
        self.assertEqual(handler.appear_calls, [IN_MAP, OS_CHECK])


if __name__ == '__main__':
    unittest.main()
