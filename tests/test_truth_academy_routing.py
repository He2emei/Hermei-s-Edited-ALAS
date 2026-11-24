import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.campaign_event import CampaignEvent
from module.coalition.assets import HORROR_COALITION_CHECK
from module.coalition.coalition import Coalition
from module.exception import ScriptError
from module.ui.assets import CAMPAIGN_MENU_GOTO_EVENT
from module.ui.page import (
    page_campaign_menu, page_coalition, page_coalition_truth, page_main,
)
from module.coalition.truth_academy import TRUTH_HOME, TRUTH_MAIN_CHECK


EVENT = 'coalition_20261124'


def campaign_event(server='cn', event=EVENT, current=None, available=True):
    return SimpleNamespace(
        config=SimpleNamespace(SERVER=server, Campaign_Event=event),
        ui_get_current_page=Mock(return_value=current),
        ui_goto=Mock(),
        is_event_entrance_available=Mock(return_value=available),
    )


class TruthAcademyRoutingTest(unittest.TestCase):
    def test_page_uses_truth_check_home_and_original_campaign_entry(self):
        self.assertIs(page_coalition_truth.check_button, TRUTH_MAIN_CHECK)
        self.assertIs(page_coalition_truth.links[page_main], TRUTH_HOME)
        self.assertIs(page_campaign_menu.links[page_coalition_truth], CAMPAIGN_MENU_GOTO_EVENT)
        self.assertIs(page_coalition.check_button, HORROR_COALITION_CHECK)

    def test_native_page_scan_skips_cn_only_assets_for_foreign_servers(self):
        from module.ui.ui import UI
        for server in ('en', 'jp', 'tw'):
            app = SimpleNamespace(config=SimpleNamespace(SERVER=server),
                                  appear=Mock(side_effect=AssertionError('CN asset accessed')))
            self.assertFalse(UI.ui_page_appear(app, page_coalition_truth))
            app.appear.assert_not_called()

    def test_native_cn_page_scan_requires_full_truth_reader(self):
        from module.ui.ui import UI
        app = SimpleNamespace(config=SimpleNamespace(SERVER='cn'),
                              device=SimpleNamespace(image=object()), appear=Mock())
        for state, expected in (('main', True), ('unknown', False), ('hard_preparation', False)):
            with patch('module.coalition.truth_academy.TruthAcademyReader') as reader:
                reader.return_value.read.return_value = state
                self.assertEqual(UI.ui_page_appear(app, page_coalition_truth), expected)
                reader.return_value.read.assert_called_once_with(app.device.image)
        app.appear.assert_not_called()

    def test_cn_event_already_on_truth_page_does_not_navigate(self):
        app = campaign_event(current=page_coalition_truth)
        self.assertTrue(CampaignEvent.ui_goto_coalition(app))
        app.ui_goto.assert_not_called()
        app.is_event_entrance_available.assert_not_called()

    def test_cn_event_uses_menu_availability_then_truth_target(self):
        app = campaign_event(current=page_campaign_menu)
        self.assertTrue(CampaignEvent.ui_goto_coalition(app))
        self.assertEqual(app.ui_goto.call_args_list, [
            unittest.mock.call(page_campaign_menu),
            unittest.mock.call(page_coalition_truth),
        ])
        app.is_event_entrance_available.assert_called_once_with()

    def test_unavailable_event_never_forces_truth_target(self):
        app = campaign_event(current=page_main, available=False)
        self.assertIsNone(CampaignEvent.ui_goto_coalition(app))
        app.ui_goto.assert_called_once_with(page_campaign_menu)
        app.is_event_entrance_available.assert_called_once_with()

    def test_non_cn_truth_event_fails_closed_without_navigation(self):
        app = campaign_event(server='en', current=page_campaign_menu)
        with self.assertRaises(ScriptError):
            CampaignEvent.ui_goto_coalition(app)
        app.ui_goto.assert_not_called()
        app.is_event_entrance_available.assert_not_called()

    def test_old_event_keeps_original_coalition_target(self):
        app = campaign_event(event='coalition_20260723', current=page_campaign_menu)
        self.assertTrue(CampaignEvent.ui_goto_coalition(app))
        self.assertEqual(app.ui_goto.call_args_list, [
            unittest.mock.call(page_campaign_menu),
            unittest.mock.call(page_coalition),
        ])

    def test_old_event_already_at_original_target_is_unchanged(self):
        app = campaign_event(event='coalition_20260723', current=page_coalition)
        self.assertTrue(CampaignEvent.ui_goto_coalition(app))
        app.ui_goto.assert_not_called()
        app.is_event_entrance_available.assert_not_called()

    def test_non_cn_old_event_keeps_original_coalition_target(self):
        app = campaign_event(server='en', event='coalition_20260723', current=page_campaign_menu)
        self.assertTrue(CampaignEvent.ui_goto_coalition(app))
        self.assertEqual(app.ui_goto.call_args_list, [
            unittest.mock.call(page_campaign_menu),
            unittest.mock.call(page_coalition),
        ])

    def test_truth_pt_ocr_fails_closed_until_roi_is_verified(self):
        app = SimpleNamespace(
            config=SimpleNamespace(SERVER='cn', Campaign_Event=EVENT),
        )
        with patch('module.coalition.coalition.Digit') as digit:
            with self.assertRaises(ScriptError):
                Coalition.get_event_pt(app)
        digit.assert_not_called()

    def test_other_locale_truth_pt_fails_closed_before_digit_construction(self):
        for server in ('jp', 'en', 'tw'):
            app = SimpleNamespace(config=SimpleNamespace(SERVER=server, Campaign_Event=EVENT))
            with patch('module.coalition.coalition.Digit') as digit:
                with self.assertRaises(ScriptError):
                    Coalition.get_event_pt(app)
            digit.assert_not_called()

    def test_oil_icon_policy_preserves_existing_event_matrix(self):
        cases = (
            ('coalition_20230323', 'cn', True),
            ('coalition_20251120', 'cn', True),
            ('coalition_20260122', 'cn', False),
            ('coalition_20260723', 'en', False),
            (EVENT, 'cn', False),
        )
        for event, server, expected in cases:
            app = SimpleNamespace(config=SimpleNamespace(Campaign_Event=event, SERVER=server))
            self.assertEqual(Coalition._coalition_has_oil_icon.fget(app), expected)

    def test_non_cn_truth_oil_policy_fails_closed(self):
        app = SimpleNamespace(config=SimpleNamespace(Campaign_Event=EVENT, SERVER='tw'))
        with self.assertRaises(ScriptError):
            Coalition._coalition_has_oil_icon.fget(app)


if __name__ == '__main__':
    unittest.main()
