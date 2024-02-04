import logging
import json
import urllib.parse
from . import bilicodes
from . import wbi

fake_headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",  # noqa
    "Accept-Charset": "UTF-8,*;q=0.5",
    "Accept-Encoding": "gzip,deflate,sdch",
    "Accept-Language": "en-US,en;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.74 Safari/537.36 Edg/79.0.309.43",  # noqa
    "Referer": "https://www.bilibili.com/",
}

# 等待依赖注入
request = None


class BiliApiError(Exception):
    def __init__(self, code: int, msg: str = None):
        self.code = code
        self.msg = msg
        if not msg and (builtin_msg := bilicodes.error_code.get(code)):
            self.msg = builtin_msg

    def __str__(self):
        return self.msg


def error_raiser(code: int, msg: str = None):
    if code != 0:
        raise BiliApiError(code, msg)


# 接口已停用
async def _get_user_info(uid: int):
    api = "https://api.bilibili.com/x/space/acc/info?mid=%s" % uid
    data = await request(api, mod="get", return_type="json", headers=fake_headers)
    error_raiser(data["code"], data["message"])
    data = data["data"]
    res = {
        "uid": data["mid"],
        "name": data["name"],
        "coin": data["coins"],
        "level": data["level"],
        "face": data["face"],
        "sign": data["sign"],
        "birthday": data["birthday"],
        "head_img": data["top_photo"],
        "sex": data["sex"],
        "vip_type": {0: "非大会员", 1: "月度大会员", 2: "年度及以上大会员"}[data["vip"]["type"]],
    }
    return res


async def get_user_info(uid: int):
    api = "https://api.bilibili.com/x/space/wbi/acc/info"
    # 进行WBI签名
    params = {"mid": uid}
    signed_params = await wbi.sign(params)
    api += "?" + urllib.parse.urlencode(signed_params)
    data = await request(api, mod="get", return_type="json", headers=fake_headers)
    error_raiser(data["code"], data["message"])
    data = data["data"]
    res = {
        "uid": data["mid"],
        "name": data["name"],
        "coin": data["coins"],
        "level": data["level"],
        "face": data["face"],
        "sign": data["sign"],
        "birthday": data["birthday"],
        "head_img": data["top_photo"],
        "sex": data["sex"],
        "vip_type": {0: "非大会员", 1: "月度大会员", 2: "年度及以上大会员"}[data["vip"]["type"]],
    }
    return res


async def get_recent(uid: int):
    api = (
        "https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?"
        "host_uid={uid}&need_top=0&platform=web".format(uid=uid)
    )
    data = await request(api, mod="get", return_type="json", headers=fake_headers)
    error_raiser(data["code"], data["msg"])
    data = data["data"]
    if "cards" in data:  # 是否发过动态
        items = [
            _dynamic_handler(desc=i["desc"], card=json.loads(i["card"]))
            for i in data["cards"]
        ]
        return items
    else:
        return []


async def get_newest(uid: int):
    data = await get_recent(uid)
    if data:
        return data
    else:
        return None


def _dynamic_handler(desc, card):
    res = {
        "dynamic_id": int(desc["dynamic_id_str"]),
        "timestamp": desc["timestamp"],
        "stat": {
            "view": desc["view"],
            "like": desc["like"],
            "forward": desc["repost"]
            # "reply":desc["comment"]
        },
        "user": desc["user_profile"]["info"],  # face,uid,uname
        "card": _card_handler(card=card, dtype=desc["type"]),
        "type": desc["type"],
    }
    return res


def _card_handler(card, dtype=2):
    if dtype == 1:  # 转发
        return _forward_card_handler(card)
    elif dtype == 2:  # 含图片
        return _common_card_handler(card)
    elif dtype == 4:  # 纯文本
        return _plaintext_card_handler(card)
    elif dtype == 8:  # 视频
        return _video_card_handler(card)
    elif dtype == 64:  # 专栏
        return _article_card_handler(card)
    elif dtype == 256:  # 音频
        return _audio_card_handler(card)
    else:
        return _unsorted_card_handler(card)


def _audio_card_handler(card):
    return {
        "content": card["intro"],
        "images": [card["cover"]],
        "audio": {
            "auid": card["id"],
            "author": card["author"],
            "desc": card["intro"],
            "stat": {"reply": card["replyCnt"], "view": card["playCnt"]},
            "cover": card["cover"],
        },
        "type": "audio",
    }


def _unsorted_card_handler(card):
    return {"content": "<未识别的动态类型>", "images": [], "type": "unknown"}


def _plaintext_card_handler(card):
    return {"content": card["item"]["content"], "images": [], "type": "plaintext"}


def _common_card_handler(card):
    return {
        "content": card["item"]["description"],
        "images": [i["img_src"] for i in card["item"]["pictures"]],
        "type": "common",
    }


def _forward_card_handler(card):
    if "origin_user" in card:
        user = card["origin_user"]["info"] # uid, face, uname
    else:
        user = None
    res = {
        "content": card["item"]["content"],
        "images": [],
        "origin": {
            "dynamic_id": card["item"]["orig_dy_id"],
            "card": None,
            "user": user, 
        },
        "type": "forward",
    }
    if "origin" in card:
        res["origin"]["card"] = _card_handler(
            card=json.loads(card["origin"]), dtype=card["item"]["orig_type"]
        )
    return res


def _video_card_handler(card):
    stat = card["stat"]
    return {
        "content": card["dynamic"],
        "images": [card["pic"]],
        "video": {
            "avid": card["aid"],
            "cid": card["cid"],
            "desc": card["desc"],
            "length": card["duration"],
            "title": card["title"],
            "tid": card["tid"],  # 分区id
            "stat": {
                "view": stat["view"],
                "coin": stat["coin"],
                "danmaku": stat["danmaku"],
                "like": stat["like"],
                "reply": stat["reply"],
                "share": stat["share"],
            }  # ,
            # "shortlink":card["short_link"]
        },
        "type": "video",
    }


def _article_card_handler(card):
    stat = card["stats"]
    return {
        "content": card["title"],
        "images": [card["banner_url"]],
        "article": {
            "cvid": card["id"],
            "title": card["title"],
            "desc": card["summary"],
            "author": {
                "uid": card["author"]["mid"],
                "uname": card["author"]["name"],
                "face": card["author"]["face"],
            },
            "stat": {
                "view": stat["view"],
                "collect": stat["favorite"],
                "like": stat["like"],
                "reply": stat["reply"],
                "coin": stat["coin"],
                "share": stat["share"],
            },
            "words": card["words"],  # 字数
        },
        "type": "article",
    }
