from .. import requester
#import requester
from loguru import logger
import json

async def get_user_info(uid):
    api = 'https://api.bilibili.com/x/space/acc/info?mid=%s'%uid
    data = await requester.aget_content_str(api)
    data = json.loads(data)
    assert data['code']==0,data['code']
    data = data['data']
    res = {
        'uid':data['mid'],
        'name':data['name'],
        'coin':data['coins'],
        'level':data['level'],
        'face':data['face'],
        'sign':data['sign'],
        'birthday':data['birthday'],
        'head_img':data['top_photo'],
        'sex':data['sex'],
        'vip_type':{0:'非大会员',1:'月度大会员',2:'年度及以上大会员'}[data['vip']['type']]
        }
    return res

async def get_newest(uid):
    api = 'https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?'\
          'host_uid={uid}&need_top=0&platform=web'.format(uid=uid)
    data = json.loads(await requester.aget_content_str(api))
    assert data['code']==0,data['code']
    data = data['data']
    if 'cards' in data: #是否发过动态
        item = data['cards'][0]
        card = json.loads(item['card'])
        desc = item['desc']
        return _dynamic_handler(desc=desc,card=card)
    else:
        return None

def _dynamic_handler(desc,card):
    res =  {
        'dynamic_id':int(desc['dynamic_id_str']),
        'timestamp':desc['timestamp'],
        'stat':{
            'view':desc['view'],
            'like':desc['like'],
            'forward':desc['repost'],
            'reply':desc['comment']
            },
        'user':desc['user_profile']['info'], #face,uid,uname
        'card':_card_handler(card=card,dtype=desc['type']),
        'type':desc['type']
        }
    return res

def _card_handler(card,dtype=2):
    if dtype == 1:#转发
        return _forward_card_handler(card)
    elif dtype == 2:#普通
        return _common_card_handler(card)
    elif dtype == 8:#视频
        return _video_card_handler(card)
    elif dtype == 64:#专栏
        return _article_card_handler(card)
    elif dtype == 256:#音频
        return _audio_card_handler(card)
    else:
        return _unsorted_card_handler(card)

def _audio_card_handler(card):
    return {
        'content':card['intro'],
        'images':[card['cover']],
        'audio':{
            'auid':card['id'],
            'author':card['author'],
            'desc':card['intro'],
            'stat':{
                'reply':card['replyCnt'],
                'view':card['playCnt']
                },
            'cover':card['cover']
            },
        'type':'audio'
        }
    
def _unsorted_card_handler(card):
    return {
        'content':'<未识别的动态类型>',
        'images':[],
        'type':'unknown'
        }

def _common_card_handler(card):
    return {
        'content':card['item']['description'],
        'images':[i['img_src'] for i in card['item']['pictures']],
        'type':'common'
        }

def _forward_card_handler(card):
    return {
        'content':card['item']['content'],
        'images':[],
        'origin':{
            'dynamic_id':card['item']['orig_dy_id'],
            'card':_card_handler(card=json.loads(card['origin']),
                                 dtype=card['item']['orig_type']),
            'user':card['origin_user']['info'] #uid,uname,face
            },
        'type':'forward'
        }

def _video_card_handler(card):
    stat = card['stat']
    return {
        'content':card['dynamic'],
        'images':[card['pic']],
        'video':{
            'avid':card['aid'],
            'cid':card['cid'],
            'desc':card['desc'],
            'length':card['duration'],
            'title':card['title'],
            'tid':card['tid'], #分区id
            'stat':{
                'view':stat['view'],
                'coin':stat['coin'],
                'danmaku':stat['danmaku'],
                'like':stat['like'],
                'reply':stat['reply'],
                'share':stat['share']
                },
            'shortlink':card['short_link']
            },
        'type':'video'
        }

def _article_card_handler(card):
    stat = card['stats']
    return {
        'content':card['title'],
        'images':card['banner_url'],
        'article':{
            'cvid':card['id'],
            'title':card['title'],
            'desc':card['summary'],
            'author':{
                'uid':card['author']['mid'],
                'uname':card['author']['name'],
                'face':card['author']['image']
                },
            'stat':{
                'view':stat['view'],
                'collect':stat['favorite'],
                'like':stat['like'],
                'reply':stat['reply'],
                'coin':stat['coin'],
                'share':stat['share']
                },
            'words':card['words']#字数
            },
        'type':'article'
        }
