import lemonyBot
from plugins.BiliDynamicForwarder import BiliDynamicForwarder
from plugins.EroPicSender import EroPicSender
from plugins.MoeAttriLottery import MoeAttriLottery
from plugins.ArknightsGacha import ArknightsGacha
from plugins.BiliLogin import BiliLogin

import logging
import os
from typing import Any
import copy
import json
import importlib
import sys

import colorama

ConfigDict = dict[str, dict | list | int | float | str]
DEFAULT_CONFIG: ConfigDict = {
    "admins": [],
    "ws_host": "127.0.0.1:5700",
    "http_host": "127.0.0.1:8000",
    "authkey": None,
}
config_file: str = "./config.json"
config: ConfigDict = None


def load_config():
    if os.path.exists(config_file):
        return json.load(open(config_file, "r", encoding="utf-8"))
    else:
        json.dump(DEFAULT_CONFIG, open(config_file, "w+", encoding="utf-8"), indent=4)
        logging.warning("config file not found, generated and using default config!")
        return copy.deepcopy(DEFAULT_CONFIG)


LOGLEVEL_COLOR_DICT = {
    logging.DEBUG: colorama.Fore.BLUE + "{}" + colorama.Fore.RESET,
    logging.INFO: colorama.Fore.GREEN + "{}" + colorama.Fore.RESET,
    logging.WARNING: colorama.Fore.YELLOW + "{}" + colorama.Fore.RESET,
    logging.ERROR: colorama.Fore.RED + "{}" + colorama.Fore.RESET,
    logging.CRITICAL: colorama.Fore.LIGHTRED_EX + "{}" + colorama.Fore.RESET,
}


def colored_filter(record: logging.LogRecord) -> bool:
    record.levelname = LOGLEVEL_COLOR_DICT[record.levelno].format(record.levelname)
    return True


logging.getLogger().addFilter(colored_filter)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG,#{True:logging.DEBUG,False:logging.WARNING}['--debug' in sys.argv],
)


config = load_config()
bot = lemonyBot.Bot(**config)
bot.set_config(admins=config["admins"])
bot.load_plugin(BiliLogin(bot))
bot.load_plugin(BiliDynamicForwarder(bot))
bot.load_plugin(EroPicSender(bot))
bot.load_plugin(MoeAttriLottery(bot))
bot.load_plugin(ArknightsGacha(bot))
bot.start()
