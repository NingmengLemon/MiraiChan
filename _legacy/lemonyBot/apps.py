from .base import SocketBase, HttpBase

import asyncio
import json
import logging


class SocketApp(SocketBase):
    # from pycqBot
    events = [
        # 好友私聊消息
        "message_private_friend",
        # 群临时会话私聊消息
        "message_private_group",
        # 群中自身私聊消息
        "message_private_group_self",
        # 私聊消息
        "message_private_other",
        # 群消息
        "message_group_normal",
        "message_group_anonymous",
        # 自身群消息上报
        "message_sent_group_normal",
        # 自身消息私聊上报
        "message_sent_private_friend",
        # 群文件上传
        "notice_group_upload",
        # 群管理员变动
        "notice_group_admin_set",
        "notice_group_admin_unset",
        # 群成员减少
        "notice_group_decrease_leave",
        "notice_group_decrease_kick",
        "notice_group_decrease_kick_me",
        # 群成员增加
        "notice_group_increase_approve",
        "notice_group_increase_invite",
        # 群禁言
        "notice_group_ban_ban",
        "notice_group_ban_lift_ban",
        # 群消息撤回
        "notice_group_recall",
        # 群红包运气王提示
        "notice_notify_lucky_king",
        # 群成员荣誉变更提示
        "notice_notify_honor",
        # 群成员名片更新
        "notice_group_card",
        # 好友添加
        "notice_friend_add",
        # 好友消息撤回
        "notice_friend_recall",
        # 好友/群内 戳一戳
        "notice_notify_poke",
        # 接收到离线文件
        "notice_offline_file",
        # 其他客户端在线状态变更
        "notice_client_status",
        # 精华消息添加
        "notice_essence_add",
        # 精华消息移出
        "notice_essence_delete",
        # 加好友请求
        "request_friend",
        # 加群请求
        "request_group_add",
        # 加群邀请
        "request_group_invite",
        # 连接响应
        "meta_event_connect",
        # 心跳
        "meta_event",
    ]

    def __init__(self, host: str, authkey: str = None) -> None:
        super().__init__(host, authkey=authkey)
        self._plugins = []

    def _get_event_name(self, event: dict):
        # from pycqBot
        event_name = event["post_type"]

        if "message_type" in event:
            event_name = "%s_%s" % (event_name, event["message_type"])
        elif "notice_type" in event:
            event_name = "%s_%s" % (event_name, event["notice_type"])
        elif "request_type" in event:
            event_name = "%s_%s" % (event_name, event["request_type"])

        if "sub_type" in event:
            event_name = "%s_%s" % (event_name, event["sub_type"])

        return event_name

    # 将接受消息重写成广播器
    def recv(self, msg: str):
        msg = json.loads(msg)
        event_name = self._get_event_name(msg)
        for plugin in self._plugins:
            method = getattr(plugin, event_name, None)
            if method:
                method(msg)
                logging.debug('broadcast to "%s" in %s' % (event_name, plugin))
            else:
                # logging.debug(
                #     'undefined method "%s" in %s, skip broadcast' % (event_name, plugin)
                # )
                pass


class HttpApp(HttpBase):
    methods = [
        # account related
        "get_login_info",
        "set_qq_profile",
        # contact related
        "get_stranger_info",
        "get_friend_list",
        "get_group_info",
        "get_group_list",
        "get_group_member_info",
        "get_group_member_list",
        "get_group_honor_info",
        "get_group_system_msg",
        "get_friend_system_msg",
        "get_essence_msg_list",
        "is_blacklist_uin",
        # user related
        # "delete_friend",  # shamrock not finished
        # message related
        "send_private_msg",
        "send_group_msg",
        "get_msg",
        "delete_msg",
        "get_history_msg",
        "get_group_msg_history",
        "clear_msgs",
        "get_forward_msg",  # bug exists
        "send_group_forward_msg",  # bug exists
        "send_private_forward_msg",
        # resource related
        "get_image",
        "get_record",
        # request related
        "set_friend_add_request",
        "set_group_add_request",
        # group related
        "set_group_name",
        "set_group_admin",
        "set_group_special_title",
        "set_group_ban",
        "set_group_whole_ban",
        "set_essence_msg",
        "delete_essence_msg",
        "send_group_sign",  # 打卡
        "_send_group_notice",
        "_get_group_notice",
        "set_group_kick",
        "set_group_leave",
        "group_touch",
        "get_prohibited_member_list",  # 被禁言列表
        "get_group_at_all_remain",  # 获取`@全体成员`剩余次数, admin only
        # file related
        "upload_private_file",  # local file only
        "upload_group_file",  # same as upper
        "delete_group_file",
        "create_group_file_folder",  # at root folder only
        "rename_group_folder",
        "delete_group_folder",
        "get_group_file_system_info",
        "get_group_root_files",
        "get_group_files_by_folder",
        "get_group_file_url",
        # other
        "get_weather_city_code",
        "get_weather",
        # shamrock unique
        "switch_account",
        "upload_file",
        "download_file",
        "get_device_battery",
        "get_start_time",
        "log",
        "shut",
    ]

    def __init__(self, host: str, authkey: str = None):
        super().__init__()
        self._http_host = host
        self._http_authkey = authkey

    async def call_api(self, method_name: str, data: dict = None):
        assert method_name in HttpApp.methods, "invalid api name: %s" % method_name
        if data is None:
            data = {}
        extra_params = {}
        if self._http_authkey:
            extra_params["headers"] = {"Authorization": self._http_authkey}
        result = await self.request(
            "http://%s/%s" % (self._http_host, method_name),
            json=data,
            return_type="json",
            mod="post",
            **extra_params
        )
        logging.debug("API > %s" % result)
        return result
