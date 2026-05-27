from yarl import URL


def get_mface_package_url(package_id: int):
    return f"https://i.gtimg.cn/club/item/parcel/0/{package_id}_android.json"


def get_mface_url(mface_id: str):
    return f"https://gxh.vip.qq.com/club/item/parcel/item/{mface_id[0:2]}/{mface_id}/raw300.gif"


def uid_to_avatar_url(uid: int) -> str:
    # return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
    return f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=png"


def avatar_url_to_uid(url: str | URL) -> int | None:
    if isinstance(url, str):
        url = URL(url)
    if url.host not in ["q.qlogo.cn", "q1.qlogo.cn"]:
        return None
    uid = url.query.get("nk") or url.query.get("dst_uin")
    if uid and uid.isdigit():
        return int(uid)
    else:
        return None


class QQInfoCache:
    """缓存QQ用户信息，避免频繁请求

    (群)头像, 昵称, 群名称"""

    # to be impl
