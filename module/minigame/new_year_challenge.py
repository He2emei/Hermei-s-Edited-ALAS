from math import isfinite

from module.base.timer import Timer
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.minigame.assets import *
from module.minigame.minigame import MINIGAME_SCROLL, MinigameRun, is_minigame_home, is_minigame_list
from module.ocr.ocr import Digit
from module.ui.page import page_game_room

OCR_GAME_NEW_YEAR_COIN_COST = Digit(NEW_YEAR_CHALLENGE_COIN_COST_HOLDER,
                                    name='OCR_GAME_NEW_YEAR_COIN_COST',
                                    letter=(33, 28, 49),
                                    threshold=128)
OCR_NEW_YEAR_BATTLE_SCORE = Digit(NEW_YEAR_CHALLENGE_SCORE_HOLDER,
                                  name='OCR_NEW_YEAR_BATTLE_SCORE',
                                  letter=(231, 215, 82),
                                  threshold=128)


class NewYearChallenge(MinigameRun):
    NEW_YEAR_BATTLE_RED = (255, 150, 123)
    NEW_YEAR_BATTLE_YELLOW = (247, 223, 115)
    NEW_YEAR_BATTLE_BLUE = (82, 134, 239)
    NEW_YEAR_BATTLE_TMP_BUTTON = [NEW_YEAR_CHALLENGE_TMP_1,
                                  NEW_YEAR_CHALLENGE_TMP_2,
                                  NEW_YEAR_CHALLENGE_TMP_3,
                                  NEW_YEAR_CHALLENGE_TMP_4,
                                  NEW_YEAR_CHALLENGE_TMP_5]
    NEW_YEAR_BATTLE_COLOR_BUTTON_DICT = {NEW_YEAR_BATTLE_RED: NEW_YEAR_CHALLENGE_RED_BUTTON,
                                         NEW_YEAR_BATTLE_YELLOW: NEW_YEAR_CHALLENGE_YELLOW_BUTTON,
                                         NEW_YEAR_BATTLE_BLUE: NEW_YEAR_CHALLENGE_BLUE_BUTTON}

    def deal_specific_popup(self):
        # enter NEW_YEAR_BATTLE first time
        if self.appear(NEW_YEAR_CHALLENGE_FIRST_TIME, offset=(5, 5), interval=3):
            self.device.click(NEW_YEAR_CHALLENGE_SAFE_AREA)
            return True
        return False

    def choose_game(self, skip_first_screenshot=True):
        self.interval_clear(page_game_room.check_button)
        scan_timeout = Timer(60, count=120).start()
        scan_phase = 'to_top'
        scroll_drags = 0
        stalled_drags = 0
        pending_position = None
        pending_phase = None
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if scan_timeout.reached():
                raise RequestHumanTakeover('New Year game list scan timed out')
            if self.deal_popup():
                continue
            # entrance
            if self.appear(NEW_YEAR_CHALLENGE_START, offset=(5, 5)):
                break
            # The home and list share GOTO_CHOOSE_GAME; only the home may navigate with it.
            if is_minigame_home(self):
                if self.appear_then_click(GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                    continue
                continue
            if not is_minigame_list(self):
                # A transition animation can briefly hide both known game-room pages.
                continue

            # Check the target on every settled list frame, even while its click is cooling down.
            if self.appear(NEW_YEAR_CHALLENGE_ENTRANCE, offset=(5, 500)):
                if self.appear(NEW_YEAR_CHALLENGE_ENTRANCE, offset=(5, 500), interval=3):
                    self.device.click(NEW_YEAR_CHALLENGE_ENTRANCE)
                    self.interval_reset(page_game_room.check_button, interval=3)
                continue

            position = MINIGAME_SCROLL.cal_position(main=self)
            if not isfinite(position):
                raise RequestHumanTakeover('Cannot measure New Year game list position')
            if pending_position is not None:
                if pending_phase == 'to_top':
                    progressed = position < pending_position - MINIGAME_SCROLL.drag_threshold
                else:
                    progressed = position > pending_position + MINIGAME_SCROLL.drag_threshold
                stalled_drags = 0 if progressed else stalled_drags + 1
                pending_position = None
                if stalled_drags >= 3:
                    if pending_phase == 'to_top':
                        # A stationary scrollbar while moving toward the top is a directional boundary.
                        scan_phase = 'scan_down'
                        stalled_drags = 0
                    else:
                        raise RequestHumanTakeover('New Year game list made no progress after 3 consecutive content swipes')

            if scan_phase == 'to_top' and position <= MINIGAME_SCROLL.edge_threshold:
                scan_phase = 'scan_down'
                stalled_drags = 0
            if scan_phase == 'scan_down' and position >= 1 - MINIGAME_SCROLL.edge_threshold:
                raise RequestHumanTakeover('New Year game not found after scanning the full list')
            if scroll_drags >= 8:
                raise RequestHumanTakeover('New Year game list scan reached 8 content swipes')

            if scan_phase == 'to_top':
                p1, p2 = (1150, 300), (1150, 450)
            else:
                p1, p2 = (1150, 450), (1150, 300)
            self.device.swipe(p1, p2, name='MINIGAME_SCROLL', distance_check=False)
            self.device.sleep(1)
            scroll_drags += 1
            pending_position = position
            pending_phase = scan_phase

    def use_coin(self, skip_first_screenshot=True):
        return self.use_coin_new_year_challenge(count=5)

    def play_game(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room new_year_challenge_prepare
            out: page_game_room new_year_challenge_end/new_year_challenge_prepare
        """
        score_ocr_interval = Timer(0.6, count=5).start()
        started = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            # a turn
            if self.appear(NEW_YEAR_CHALLENGE_CHOOSING, offset=(5, 5), interval=3):
                # choose, click on clock to avoid be detected as "Too many click between 2 buttons"
                # self.device.click(NEW_YEAR_CHALLENGE_CHOOSING)
                self.new_year_challenge_turn(skip_first_screenshot=False)
                self.device.click_record_clear()
                continue
            # wait to choose
            if score_ocr_interval.reached() and self.appear(NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5)):
                # score is enough, stop play
                score = OCR_NEW_YEAR_BATTLE_SCORE.ocr(self.device.image)
                score_ocr_interval.reset()
                if score > 1000 and self.appear_then_click(NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5), interval=3):
                    continue
            # finished
            if self.appear(NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                break
            # game rule introduction
            if self.appear(NEW_YEAR_CHALLENGE_START, offset=(5, 5), interval=3):
                if started:
                    self.interval_clear(NEW_YEAR_CHALLENGE_START)
                    break
                else:
                    started = True
                    self.device.click(NEW_YEAR_CHALLENGE_START)
                    continue

    def exit_game(self, skip_first_screenshot=True):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(BACK, offset=(5, 5)):
                if is_minigame_list(self):
                    break
                if is_minigame_home(self):
                    if self.appear_then_click(GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                        continue
                elif self.appear(NEW_YEAR_CHALLENGE_END, offset=(5, 5)) \
                        or self.appear(NEW_YEAR_CHALLENGE_EXIT, offset=(5, 5)) \
                        or self.appear(NEW_YEAR_CHALLENGE_START, offset=(5, 5)):
                    self.appear_then_click(BACK, offset=(5, 5), interval=3)
                    continue
            if self.appear_then_click(NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(NEW_YEAR_CHALLENGE_EXIT, offset=(5, 5), interval=3):
                continue

    def use_coin_new_year_challenge(self, skip_first_screenshot=True, count=1):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(NEW_YEAR_CHALLENGE_ADD_COIN, offset=(5, 5)):
                # add coins
                if count > 1:
                    for i in range(count - 1):
                        self.device.click(NEW_YEAR_CHALLENGE_ADD_COIN)
                    self.device.screenshot()
                # spend no coins for test
                if count < 1:
                    self.appear_then_click(NEW_YEAR_CHALLENGE_DEC_COIN, offset=(5, 5), interval=3)
                    self.device.screenshot()
                coin_cost_after_add = OCR_GAME_NEW_YEAR_COIN_COST.ocr(self.device.image)
                logger.info(f"coin cost after add : {coin_cost_after_add}")
                if count >= 1 and coin_cost_after_add <= 0:
                    # can't add coin because all monthly reward is gotten or coin left is 0
                    return False
                return True

    def new_year_challenge_turn(self, skip_first_screenshot=True):
        if not skip_first_screenshot:
            self.device.screenshot()
        to_clicks = []
        # judge to click
        for to_judge in self.NEW_YEAR_BATTLE_TMP_BUTTON:
            for color, button in self.NEW_YEAR_BATTLE_COLOR_BUTTON_DICT.items():
                if self.image_color_count(to_judge, color, threshold=30, count=10):
                    to_clicks.append(button)
                    break
        logger.info(f"to clicks: {to_clicks}")
        to_clicks.reverse()
        # click
        click_interval = Timer(0.2, count=5).start()
        while 1:
            if to_clicks and click_interval.reached():
                self.device.click(to_clicks.pop())
                click_interval.reset()
            if not to_clicks:
                break
