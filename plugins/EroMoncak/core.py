from melobot import Plugin, send_text
from melobot.protocols.onebot.v11 import on_regex_match, on_message
from melobot.protocols.onebot.v11.adapter.event import MessageEvent


@on_regex_match(r"^[好][色涩瑟][情]?$")
def say_ero(event: MessageEvent):
    raise NotImplementedError()

class EroMoncak(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = []