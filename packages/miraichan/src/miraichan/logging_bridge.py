"""把标准库 logging 接到 melobot 日志器上。

插件、共享库和第三方库 (sqlalchemy 等) 一律用 ``logging.getLogger(__name__)``,
不依赖 melobot。这里在 root logger 上挂一个转发 handler, 把记录交给 melobot
全局日志器的 handler 输出, 于是:

- 级别过滤完全走标准 logging 的层级: root 级别由 debug 开关决定,
  个别子树 (``sqlalchemy.engine``、``mbplugin_recorder`` 等) 可以单独调;
- 模块不需要知道自己是否处于 debug 模式, 也不需要 bot 实例。
"""

import logging
from collections.abc import Mapping

from melobot.log import Logger

_LEVEL_NAMES = logging.getLevelNamesMapping()


class MelobotForwardHandler(logging.Handler):
    """把 stdlib LogRecord 转交给 melobot Logger 的 handler"""

    def __init__(self, target: Logger) -> None:
        super().__init__(logging.NOTSET)
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # melobot 的 formatter 依赖它自己 makeRecord 填的字段
            if not hasattr(record, "mod_name"):
                record.mod_name = record.name  # type: ignore[attr-defined]
                record.func_lineno = record.lineno  # type: ignore[attr-defined]
            # melobot 的 filter 负责填充格式化所需的 msg_str / log_info
            for flt in self._target.filters:
                if isinstance(flt, logging.Filter):
                    flt.filter(record)
                elif callable(flt):
                    flt(record)
            for handler in self._target.handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)
        except Exception:  # noqa: BLE001  logging.Handler 约定: 交给 handleError
            self.handleError(record)


def parse_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    try:
        return _LEVEL_NAMES[value.upper()]
    except KeyError:
        raise ValueError(f"unknown log level: {value!r}") from None


def install_logging_bridge(
    target: Logger,
    *,
    root_level: int,
    levels: Mapping[str, str | int] | None = None,
) -> MelobotForwardHandler:
    """在 root logger 上安装转发 handler, 并设置各子树级别。可重复调用"""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, MelobotForwardHandler):
            root.removeHandler(h)
    handler = MelobotForwardHandler(target)
    root.addHandler(handler)
    root.setLevel(root_level)
    for name, level in (levels or {}).items():
        logging.getLogger(name).setLevel(parse_level(level))
    return handler
