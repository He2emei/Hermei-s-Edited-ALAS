import unittest
from types import SimpleNamespace
from unittest import mock

from module.shipyard.assets import SHIPYARD_MINUS_DEV, SHIPYARD_MINUS_FATE
from module.shipyard.auto import AutoShipyard
from module.exception import RequestHumanTakeover


class ShipyardUnstartedProjectTest(unittest.TestCase):
    """A panel that cannot be adjusted must be skipped, never waited on.

    Live frames 2026-09-19 (埃吉尔, 科研四期): the project had not been researched
    far enough, so the panel offered 开始研究 and had no quantity row at all —
    verified by re-checking the archived frames: none of the shipyard templates
    matched, including SHIPYARD_MINUS_DEV and SHIPYARD_MINUS_FATE.  AutoShipyard
    nevertheless entered _use_owned, waited for those controls, and raised
    GameStuckError every few minutes until the guard stopped restarting the
    scheduler.
    """

    def test_quantity_controls_decide_adjustability(self):
        class Fake(AutoShipyard):
            def __init__(self, visible):
                self.visible = visible

            def appear(self, button, offset=0):
                return button in self.visible

        self.assertFalse(Fake(set())._quantity_controls_visible())
        self.assertTrue(Fake({SHIPYARD_MINUS_DEV})._quantity_controls_visible())
        self.assertTrue(Fake({SHIPYARD_MINUS_FATE})._quantity_controls_visible())

    def test_candidate_without_controls_is_unbuilt(self):
        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def _quantity_controls_visible(self):
                return False

            def _use_owned(self, index):
                raise AssertionError('quantity handling must not be reached')

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        with mock.patch('module.shipyard.auto.required_level', return_value=None):
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', False), 'unbuilt')

    def test_candidate_still_uses_owned_blueprints_when_controls_exist(self):
        calls = []

        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def _quantity_controls_visible(self):
                return True

            def _use_owned(self, index):
                calls.append(index)
                return False

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        with mock.patch('module.shipyard.auto.required_level', return_value=None):
            with mock.patch.object(Fake, 'auto_full', return_value=False):
                self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', False), 'retry')
        # The owned-blueprint path is reached exactly once, then the candidate
        # reports retry; it must not fall through to the quantity controls again.
        self.assertEqual(calls, [1])

    def test_unreadable_level_target_defers_instead_of_stopping_the_pass(self):
        """One bad level target must not end the whole daily catch-up.

        Live 2026-09-19 04:38: the Shipyard pass died with "Request human
        takeover" while scanning the dock for a level target, which stopped the
        scheduler and, with it, every later task in the queue.
        """

        class Fake(AutoShipyard):
            def auto_enter(self):
                return True

            def auto_fate(self):
                return False

            def auto_full(self):
                return False

            def ui_ensure(self, page):
                return None

        fake = Fake.__new__(Fake)
        fake.device = SimpleNamespace(image=None)
        fake.config = SimpleNamespace(ShipyardAuto_UseExpBooks=True)
        with mock.patch('module.shipyard.auto.required_level', return_value=10), \
                mock.patch('module.shipyard.auto.ShipyardLeveler') as leveler:
            leveler.return_value.meet_level.side_effect = RequestHumanTakeover(
                'dock filter does not surface the level target')
            self.assertEqual(fake._candidate(4, 1, '埃吉尔', 'DR', True), 'level')


if __name__ == '__main__':
    unittest.main()
