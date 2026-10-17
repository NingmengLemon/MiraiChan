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
    """键对应的环境变量名, 例如 ``websocket.access_token`` -> ``MIRAICHAN_WEBSOCKET_ACCESS_TOKEN``"""
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
    """同 :func:`get_secret`, 但取不到时抛 KeyError (启动阶段用)"""
    value = get_secret(key, env_prefix=env_prefix)
    if value is None:
        raise KeyError(
            f"缺少凭据 {key!r}: 请写进凭据文件, 或设置环境变量 {env_name(key, env_prefix)}"
        )
    return value


def ensure_credentials_file(
    path: str | Path | None = None,
    *,
    template: Mapping[str, str] | None = None,
) -> Path:
    """确保凭据文件存在; 新建时写一份模板, 权限 0600。

    已存在时不动它 (只把权限记录到警告里, 交给 :func:`warn_if_insecure`)。
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
        # 另一个进程刚好抢先建好了, 用它就行, 不要覆盖
        return target
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
    finally:
        # Windows 上 mode 参数基本无效, 这里显式收一次权限 (Linux 上就是 0600)
        with contextlib.suppress(OSError):
            os.chmod(target, 0o600)
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
