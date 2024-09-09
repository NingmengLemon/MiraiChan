from .apps import SocketApp, HttpApp


class Bot(SocketApp, HttpApp):
    def __init__(
        self,
        ws_host: str = "127.0.0.1:5700",
        http_host: str = "127.0.0.1:8000",
        authkey: str = None,
        **trash
    ) -> None:
        SocketApp.__init__(self, ws_host, authkey=authkey)
        HttpApp.__init__(self, http_host, authkey=authkey)

        # 这个 config 字典是供插件读取的
        # 往后可能会扩充
        self.config = {
            "admins": [],
        }

    def start(self):
        SocketApp.start(self)

    def load_plugin(self, plugin_instance):
        self._plugins += [plugin_instance]

    def set_config(self, **kwargs):
        for k, v in kwargs.items():
            self.config[k] = v
