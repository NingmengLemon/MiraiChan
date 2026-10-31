from collections.abc import Mapping


class LemonyProgrammingError(Exception):
    """出现这个错误是你搞砸了"""


class LemonyInternalImplError(Exception):
    """出现这个错误是我搞砸了"""


class CheckerSettingsSaveError(Exception):
    """保存检查器配置失败.

    内存中已修改的目标会按快照回滚; ``failures`` 记录每个失败目标对应的原始异常,
    键为 ``"global"`` 或插件名.
    """

    def __init__(self, failures: Mapping[str, BaseException]) -> None:
        self.failures: dict[str, BaseException] = dict(failures)
        targets = ", ".join(sorted(self.failures))
        super().__init__(f"failed to save checker settings: {targets}")
