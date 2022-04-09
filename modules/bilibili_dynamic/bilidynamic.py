from . import requester
#import requester
from loguru import logger
import json

async def get_newest(uid):
    api = 'https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?'\
          'host_uid={uid}&need_top=0&platform=web'.format(uid=uid)
    data = await requester.aget_content_str(api)
    logger.info(f'Fetch newest dynamic of uid{uid}')
    data = json.loads(data)['data']
    if 'cards' in data:
        card = data['cards'][0]
        desc = card['desc']
        detail = json.loads(card['card'])
        if 'origin' in detail:
            is_forward = True
            org = json.loads(detail['origin'])
            if 'content' in org['item']:
                orgc = org['item']['content']
            else:
                orgc = org['item']['description']
            forward_info = {
                'user':detail['origin_user']['info'],#uid,uname,face
                'item':{
                    'dynamic_id':int(desc['origin']['dynamic_id_str']),
                    'content':orgc,
                    'timestamp':desc['origin']['timestamp'],
                    'reply':org['item']['reply']
                    }
                }
        else:
            is_forward = False
            forward_info = None
        if 'pictures' in detail['item']:
            images = [i['img_src'] for i in detail['item']['pictures']]
        else:
            images = []
        if 'content' in detail['item']:
            content = detail['item']['content']
        else:
            content = detail['item']['description']
        return {
            'dynamic_id':int(desc['dynamic_id_str']),
            'timestamp':desc['timestamp'],
            'user':desc['user_profile']['info'], #有uid,uname,face
            'content':content,
            'images':images,
            'is_forward':is_forward,
            'forward_info':forward_info
            }
    else:
        return None

def get_newest_new(uid):
    api = 'https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?'\
          'host_uid={uid}&need_top=0&platform=web'.format(uid=uid)
    data = json.loads(requester.get_content_str(api))
    assert data['code']==0,'BiliCode {code}: {msg}'.format(**data)
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
    else:
        return _unsorted_card_handler(card)

def _unsorted_card_handler(card):
    return {
        'content':'未知的动态类型',
        'image':[],
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
                }
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
                'face':card['author']['image'],
                'stat':{
                    'view':stat['view'],
                    'collect':stat['favorite'],
                    'like':stat['like'],
                    'reply':stat['reply'],
                    'coin':stat['coin'],
                    'share':stat['share']
                    },
                'words':card['words']#字数
                }
            },
        'type':'article'
        }
