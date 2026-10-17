"""凭据存储: 秘密值不写进普通配置。

普通配置 (根 ``config.json`` 与 ``configs/`` 下的插件配置) 是给人看、进备份、可以分享的,
凭据单独放: 一个扁平的 JSON 文件, 或者环境变量。

凭据文件长这样, 键用点号分层, 只用于查找::

    {
        "websocket.access_token": "...",
        "quote.api_key": "..."
    }

读取顺序是 **环境变量 > 凭据文件**。环境变量名由前缀和键拼出来: 键里非字母数字的字符
变成下划线, 大写, 前面加上 ``<前缀>_``, 例如 ``MIRAICHAN_WEBSOCKET_ACCESS_TOKEN``。
空字符串按"没设置"处理。

文件由 :func:`ensure_credentials_file` 创建, POSIX 下权限是 0600;
:func:`warn_if_insecure` 会在文件对同组或其他用户可读时打警告。
"""

import contextlib
import json
import logging
import os
import stat
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "DEFAULT_ENV_PREFIX",
    "CredentialsFileError",
    "MissingCredentialError",
    "ensure_credentials_file",
    "env_name",
    "get_credentials_path",
    "get_secret",
    "load_credentials",
    "require_secret",
    "set_credentials_path",
    "warn_if_insecure",
]

DEFAULT_ENV_PREFIX = "MIRAICHAN"

logger = logging.getLogger(__name__)

_credentials_path: Path | None = None
# (路径, mtime_ns, 大小) -> 内容, 文件被外部改写后自动失效
_cache: tuple[tuple[str, int, int], dict[str, str]] | None = None


class CredentialsFileError(ValueError):
    """凭据文件格式不对 (不是 JSON 对象, 或者值不是字符串)"""


class MissingCredentialError(LookupError):
    """需要的凭据既不在环境变量里也不在凭据文件里"""


def set_credentials_path(path: str | Path | None) -> None:
    """设定凭据文件位置; 传 None 清除 (测试用)"""
    global _credentials_path
    _credentials_path = Path(path) if path is not None else None


def get_credentials_path() -> Path | None:
    return _credentials_path


def _read_file(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise CredentialsFileError(f"{path} 不是合法的 JSON: {exc}") from exc
    except OSError as exc:
        # 路径是个目录、没权限读之类: 说清楚是哪个文件, 而不是抛一个裸的 OSError
        raise CredentialsFileError(f"{path} 无法读取: {exc}") from exc
    if not isinstance(raw, dict):
        raise CredentialsFileError(f"{path} 的顶层必须是对象")
    data: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise CredentialsFileError(f"{path} 中 {key!r} 的值必须是字符串")
        data[str(key)] = value
    return data


def load_credentials() -> dict[str, str]:
    """读取凭据文件 (没有设置路径或文件不存在时返回空字典)"""
    global _cache
    path = _credentials_path
    if path is None:
        return {}
    try:
        info = path.stat()
    except FileNotFoundError:
        _cache = None
        return {}
    signature = (str(path), info.st_mtime_ns, info.st_size)
    if _cache is not None and _cache[0] == signature:
        return dict(_cache[1])
    data = _read_file(path)
    _cache = (signature, data)
    return dict(data)


def env_name(key: str, prefix: str = DEFAULT_ENV_PREFIX) -> str:
    """键对应的环境变量名, 例如 ``websocket.access_token`` -> ``MIRAICHAN_WEBSOCKET_ACCESS_TOKEN``

    映射是有损的: 非字母数字一律变成下划线, 所以 ``a.b_c`` 与 ``a_b.c`` 会撞到同一个
    环境变量名。键的命名要自己避开这种形状。
    """
    normalized = "".join(ch if ch.isalnum() else "_" for ch in key).upper()
    return f"{prefix}_{normalized}" if prefix else normalized


def get_secret(key: str, *, env_prefix: str = DEFAULT_ENV_PREFIX) -> str | None:
    """取一个凭据: 环境变量优先, 其次凭据文件; 没设置或为空返回 None"""
    from_env = os.environ.get(env_name(key, env_prefix))
    if from_env:
        return from_env
    value = load_credentials().get(key)
    return value or None


def require_secret(key: str, *, env_prefix: str = DEFAULT_ENV_PREFIX) -> str:
    """同 :func:`get_secret`, 但取不到时抛 :class:`MissingCredentialError` (启动阶段用)"""
    value = get_secret(key, env_prefix=env_prefix)
    if value is None:
        raise MissingCredentialError(
            f"缺少凭据 {key!r}: 请写进凭据文件, 或设置环境变量 {env_name(key, env_prefix)}"
        )
    return value


def ensure_credentials_file(
    path: str | Path | None = None,
    *,
    template: Mapping[str, str] | None = None,
) -> Path:
    """确保凭据文件存在; 新建时写一份模板。

    POSIX 下新文件的权限是 0600, Windows 上只把只读位打开 (mode 位在 Windows 上不代表 ACL)。
    已存在时不动它 (权限问题交给 :func:`warn_if_insecure`)。
    """
    target = Path(path) if path is not None else _credentials_path
    if target is None:
        raise ValueError("凭据文件路径未设置")
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(dict(template or {}), indent=4, ensure_ascii=False) + "\n"
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # 另一个进程刚好抢先建好了 (用它就行); 也可能路径是个目录 / 悬空符号链接
        if not target.is_file():
            logger.warning("凭据路径 %s 已存在但不是普通文件, 没有创建凭据文件", target)
        return target
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
    except BaseException:
        # 写到一半失败 (磁盘满之类) 不能留下半个文件, 否则之后每次启动都解析失败
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        raise
    finally:
        with contextlib.suppress(OSError):
            os.chmod(target, 0o600)
    if os.name == "nt":
        logger.info("已创建凭据文件 %s, 把凭据填进去", target)
    else:
        logger.info("已创建凭据文件 %s, 把凭据填进去 (权限 0600)", target)
    return target


def warn_if_insecure(path: str | Path | None = None) -> bool:
    """凭据文件对同组或其他用户可读时打警告; 返回是否发现了问题。

    只在 POSIX 上检查: Windows 的权限模型不看 mode 位。
    """
    target = Path(path) if path is not None else _credentials_path
    if target is None or os.name == "nt":
        return False
    try:
        mode = target.stat().st_mode
    except FileNotFoundError:
        return False
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "凭据文件 %s 的权限是 %o, 同组或其他用户也能读; 建议 chmod 600",
            target,
            stat.S_IMODE(mode),
        )
        return True
    return False
