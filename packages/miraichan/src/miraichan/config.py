import copy
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from lemony_settings import get_secret
from pydantic import BaseModel, Field, Secret

from .utils import get_project_root

DEFAULT_CONFIG_PATH = get_project_root() / "config.json"
DEFAULT_CREDENTIALS_PATH = get_project_root() / "credentials.json"
# 线上用 `mb run` 启动时只透传入口文件, 没法把 CLI 参数转给 miraichan, 改位置走这个环境变量
CREDENTIALS_PATH_ENV = "MIRAICHAN_CREDENTIALS_PATH"

# 允许从凭据文件 / 环境变量覆盖到根配置里的键。凭据只用于这些查找,
# 不参与配置校验, 所以不会把别的配置项(比如插件列表)意外覆盖掉
CREDENTIAL_KEYS = ("websocket.access_token",)


def resolve_credentials_path(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """凭据文件位置: 命令行参数 > 环境变量 > 项目根下的 ``credentials.json``

    相对路径按进程工作目录解析 (启动时会先切到项目根)。
    """
    env = os.environ if environ is None else environ
    raw = explicit or env.get(CREDENTIALS_PATH_ENV) or DEFAULT_CREDENTIALS_PATH
    return Path(raw)


def apply_credential_overrides(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把凭据里的值覆盖到原始配置上, 返回一份新的 dict。

    读取顺序由 ``lemony_settings.credentials`` 决定 (环境变量优先, 其次凭据文件);
    取不到值的键保持原样。缺的中间层会补成对象, 结构不对时交给 pydantic 报错。
    """
    data = copy.deepcopy(dict(raw))
    for key in CREDENTIAL_KEYS:
        value = get_secret(key)
        if value is None:
            continue
        *parents, leaf = key.split(".")
        node: dict[str, Any] = data
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[leaf] = value
    return data


def plaintext_token_present(raw: Mapping[str, Any]) -> bool:
    """配置里是否还留着明文的 websocket.access_token"""
    websocket = raw.get("websocket")
    return isinstance(websocket, dict) and bool(websocket.get("access_token"))


class WebsocketIOConfigModel(BaseModel):
    access_token: Secret[str | None] = Secret(None)
    cd_time: int = Field(default=0, ge=0)


class ReverseWebsocketIOConfigModel(WebsocketIOConfigModel):
    host: str = "127.0.0.1"
    port: int = Field(default=10721, ge=0)
    type: Literal["reverse"] = "reverse"


class ForwardWebsocketIOConfigModel(WebsocketIOConfigModel):
    url: str = "ws://127.0.0.1:10721"
    type: Literal["forward"] = "forward"


class GlobalConfigModel(BaseModel):
    debug: bool = False
    websocket: ForwardWebsocketIOConfigModel | ReverseWebsocketIOConfigModel = Field(
        discriminator="type", default_factory=lambda: ForwardWebsocketIOConfigModel()
    )

    load_depth: int = 3
    plugins: list[str] = []

    settings_format: Literal["json", "yaml"] | str = "json"
    config_root: str | Path = Field(default=(Path("configs")).as_posix())

    # 标准 logging 的子树级别覆盖, 例如 {"sqlalchemy.engine": "INFO"} 打开 SQL 日志,
    # {"mbplugin_recorder": "DEBUG"} 只给一个插件开 debug。root 级别由 debug 决定
    log_levels: dict[str, str] = {}

    default_font_path: str | Path = Field(
        default=(Path("data") / "fonts" / "sarasa-mono-sc-semibold.ttf").as_posix()
    )
