"""Strict CN search-complete recovery shared by UI entry and OpSi loops."""
import time
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from module.base.button import Button
from module.exception import RequestHumanTakeover

@lru_cache(maxsize=1)
def _templates():
    root=Path(__file__).resolve().parents[2]/'assets/cn/os_handler'
    result=[]
    for name in ('search_reward_title_cn.png','search_reward_continue_cn.png'):
        image=cv2.imread(str(root/name))
        if image is None:
            raise RequestHumanTakeover('CN search reward text asset missing')
        result.append(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    return tuple(result)

def read_os_search_reward(image):
    if image is None or getattr(image,'shape',None)!=(720,1280,3) or getattr(image,'dtype',None)!=np.uint8:
        return None
    found=[]
    for template,search,expected in zip(_templates(),
            ((530,180,780,270),(555,450,735,530)),((565,204),(595,478))):
        left,top,right,bottom=search
        scores=cv2.matchTemplate(image[top:bottom,left:right],template,cv2.TM_CCOEFF_NORMED)
        _,score,_,location=cv2.minMaxLoc(scores)
        x,y=left+location[0],top+location[1]
        if score<.99 or abs(x-expected[0])>3 or abs(y-expected[1])>3:
            return None
        observed=image[y:y+template.shape[0],x:x+template.shape[1]]
        difference=np.abs(observed.astype(np.int16)-template.astype(np.int16))
        if float(difference.mean())>12 or float((difference<20).all(axis=2).mean())<.97:
            return None
        found.append((int(x),int(y),int(x+template.shape[1]),int(y+template.shape[0])))
    return Button(area=found[1],color=(0,0,0),button=found[1],
                  name='OS_SEARCH_REWARD_CONTINUE')

def reset_os_search_reward(main):
    # Only native known-page / visible-map callers may reset this budget.
    main._os_search_reward_recovery=None

def handle_os_search_reward(main):
    config=getattr(main,'config',None)
    command=getattr(getattr(config,'task',None),'command',None)
    if getattr(config,'SERVER',None)!='cn' or not isinstance(command,str) or not command.startswith('Opsi'):
        return False
    before=read_os_search_reward(main.device.image)
    if before is None:
        return False
    state=getattr(main,'_os_search_reward_recovery',None)
    if state is not None and time.monotonic()-state['last_click']<2:
        return True
    positions=[]
    for observation in range(2):
        if observation:
            main.device.sleep(.3)
        main.device.screenshot()
        button=read_os_search_reward(main.device.image)
        if button is None:
            return False
        positions.append(tuple(int(v) for v in button.button))
    if positions[0]!=positions[1] or positions[0]!=tuple(int(v) for v in before.button):
        return False
    if state is None:
        state={'attempts':0,'last_click':0.0}
        main._os_search_reward_recovery=state
    if state['attempts']>=3:
        message='CN search-complete reward persisted after three dismiss attempts'
        if command=='OpsiCrossMonth':
            message=('Overdue OpsiCrossMonth cannot confirm the old Operation Siren map because '
                     +message+'; preserve NextRun and use SkipPendingCatchUp only after '
                     'explicit confirmation that old-month work is complete or unavailable.')
        raise RequestHumanTakeover(message)
    # Record the attempt before issuing the only permitted continuation click.
    state['attempts']+=1
    state['last_click']=time.monotonic()
    main.device.click(button)
    return True
