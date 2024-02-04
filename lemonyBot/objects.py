
from . import cqcode
from .apps import HttpApp, SocketApp

class Plugin:
    def __init__(self, bot):
        self.bot = bot
        self.__create_api_methods()

    def __create_api_methods(self):
        for mname in HttpApp.methods:
            self.__method_maker(mname)

    def __method_maker(self, method_name):
        async def method_a(data):
            return await self.bot.call_api(method_name=method_name, data=data)
        def method_f(data):
            self.bot.add_task(self.bot.call_api(method_name=method_name, data=data))

        setattr(self, method_name+'_async', method_a)
        setattr(self, method_name+'_func', method_f)

    @property
    def config(self):
        return self.bot.config
    
    @property
    def admins(self):
        return self.bot.config.get("admins")