import json
import random
import time
import os
import logging
import atexit
import re
import asyncio
import threading
import yaml

# 依赖注入, 小子
request = None

cache = []
cache_lock = threading.Lock()
cache_file = "./data/setu_cache.json"
if os.path.isfile(cache_file):
    cache = json.load(open(cache_file, "r", encoding="utf-8"))

history_path_req = "./data/setu_history/datapacks/"
if not os.path.exists(history_path_req):
    os.makedirs(history_path_req, exist_ok=True)


@atexit.register
def save_cache():
    json.dump(cache, open(cache_file, "w+", encoding="utf-8"))


async def lolicon_api(n=20):
    data = await request(
        f"https://api.lolicon.app/setu/v2?r18=0&num={n}", mod="get", return_type="json"
    )
    assert not bool(data["error"]), data["error"]
    return data["data"]


async def fetch():
    global cache
    logging.debug("fetching new setu...")
    data = await lolicon_api()
    flag = "lolicon"
    filename = str(time.time()) + "_" + flag + ".json"
    with open(os.path.join(history_path_req, filename), "w+", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    with cache_lock:
        cache += data
    logging.debug("fetched %s packs, %s left in cache" % (len(data), len(cache)))


def get_datapack():
    global cache
    if cache:
        with cache_lock:
            data = cache.pop(random.randint(0, len(cache) - 1))
        logging.debug("popped new setu package, %d left"%len(cache))
        return data
    else:
        return None


def get_msg():
    global cache
    if cache:
        data = get_datapack()
        url = data["urls"]["original"]#.replace("i.pixiv.re","pixrev.lemonyaweb.top")
        url_cut = "/" + url.split("/", 3)[-1]
        msg = "URL: " + url_cut
        msg += """
PixivID: {pid}
Author: {uid} ({author})
Size: {width}x{height}
Tags:
#{tags_formatted}#""".format(
            **data, tags_formatted="# #".join(data["tags"])
        )
        return url, msg
    else:
        return None, "后台缓存为空，请联系管理员"
