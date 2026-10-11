"""标准 logging 到 melobot 日志器的转发与级别控制"""

import logging
from collections.abc import Iterator

import pytest
from melobot.log import Logger, LogLevel
from miraichan.logging_bridge import (
    MelobotForwardHandler,
    install_logging_bridge,
    parse_level,
)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def target() -> Iterator[tuple[Logger, _ListHandler]]:
    melo = Logger("bridge-test", level=LogLevel.DEBUG, to_console=False)
    sink = _ListHandler()
    melo.addHandler(sink)
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, list(root.handlers)
    touched = ["bridge_test_pkg", "bridge_test_pkg.sub", "sqlalchemy.engine"]
    saved_child = {n: logging.getLogger(n).level for n in touched}
    yield melo, sink
    for h in list(root.handlers):
        if isinstance(h, MelobotForwardHandler):
            root.removeHandler(h)
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for n, lvl in saved_child.items():
        logging.getLogger(n).setLevel(lvl)


def test_records_below_root_level_are_dropped(
    target: tuple[Logger, _ListHandler],
) -> None:
    melo, sink = target
    install_logging_bridge(melo, root_level=logging.INFO)
    log = logging.getLogger("bridge_test_pkg.sub")

    log.debug("hidden")
    log.info("shown %d", 1)

    assert [r.getMessage() for r in sink.records] == ["shown 1"]
    assert sink.records[0].mod_name == "bridge_test_pkg.sub"  # type: ignore[attr-defined]


def test_subtree_level_override_enables_debug_for_one_package(
    target: tuple[Logger, _ListHandler],
) -> None:
    melo, sink = target
    install_logging_bridge(
        melo, root_level=logging.INFO, levels={"bridge_test_pkg": "DEBUG"}
    )

    logging.getLogger("bridge_test_pkg.sub").debug("pkg debug")
    logging.getLogger("other_pkg").debug("other debug")

    assert [r.getMessage() for r in sink.records] == ["pkg debug"]


def test_sqlalchemy_engine_logs_only_when_its_logger_is_enabled(
    target: tuple[Logger, _ListHandler],
) -> None:
    # SQL 日志由 sqlalchemy.engine 的级别决定, 而不是 create_engine(echo=...)
    melo, sink = target
    install_logging_bridge(melo, root_level=logging.DEBUG)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").info("SELECT 1")
    assert sink.records == []

    install_logging_bridge(
        melo, root_level=logging.INFO, levels={"sqlalchemy.engine": "INFO"}
    )
    logging.getLogger("sqlalchemy.engine.Engine").info("SELECT 2")
    assert [r.getMessage() for r in sink.records] == ["SELECT 2"]


def test_reinstall_does_not_duplicate_handlers(
    target: tuple[Logger, _ListHandler],
) -> None:
    melo, sink = target
    install_logging_bridge(melo, root_level=logging.INFO)
    install_logging_bridge(melo, root_level=logging.INFO)

    logging.getLogger("bridge_test_pkg").info("once")

    assert len(sink.records) == 1


def test_parse_level_rejects_unknown_names() -> None:
    assert parse_level("debug") == logging.DEBUG
    with pytest.raises(ValueError, match="unknown log level"):
        parse_level("verbose")
