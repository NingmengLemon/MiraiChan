from __future__ import annotations

import json
import random
import re
from importlib import resources

from melobot.log import get_logger

from . import resources as res_module
from .typedefs import AttrPool, MoeData, Weight

logger = get_logger()


def weighted_choice(options: dict[str, Weight]) -> str:
    """从带权重的选项字典中随机选取一个"""
    keys = list(options.keys())
    weights = [options[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


class LotteryBox:
    def __init__(self, moefile: str | None = None) -> None:
        self._data = self._load(moefile)

    @staticmethod
    def _load(moefile: str | None = None) -> MoeData:
        if moefile is None:
            raw = (resources.files(res_module) / "moe_attrs.json").read_text(
                encoding="utf-8"
            )
            return MoeData.model_validate_json(raw)
        with open(moefile, "r", encoding="utf-8") as fp:
            return MoeData.model_validate(json.load(fp))

    # ---- 抽取 ----

    @staticmethod
    def _draw_from_pool(pool: AttrPool, drawn: dict[str, str | None]) -> str | None:
        """从单个属性池中抽取结果

        - 独立池（无 depends_on）：直接从 options 中加权随机
        - 条件池（有 depends_on）：先看依赖池的结果是否命中 triggers，
          命中了才从对应选项中抽取，否则返回 None
        - nullable 池：有 null_weight 概率返回 None
        """
        if pool.depends_on is not None:
            dep = pool.depends_on
            dep_value = drawn.get(dep.pool)
            if dep_value is None or dep_value not in dep.triggers:
                return None
            return weighted_choice(dep.triggers[dep_value])

        if pool.options is None:
            return None

        if pool.nullable and pool.null_weight > 0:
            # 把"无结果"也作为一个带权重的选项参与抽取
            total = sum(pool.options.values()) + pool.null_weight
            if random.uniform(0, total) < pool.null_weight:
                return None

        return weighted_choice(pool.options)

    def lot(self) -> dict[str, str | None]:
        """执行一次完整抽取，返回 {池名: 抽取结果}"""
        pools = self._data.pools
        drawn: dict[str, str | None] = {}

        # 第一轮：抽取所有独立池（无 depends_on 的池）
        for name, pool in pools.items():
            if pool.depends_on is None:
                drawn[name] = self._draw_from_pool(pool, drawn)

        # 第二轮：抽取所有条件池（有 depends_on 的池）
        for name, pool in pools.items():
            if pool.depends_on is not None:
                drawn[name] = self._draw_from_pool(pool, drawn)

        logger.debug(f"抽取结果: {drawn}")
        return drawn

    # ---- 文本构建 ----

    def build_response_text(self, drawn: dict[str, str | None]) -> str:
        """根据抽取结果和模板生成最终的描述文本"""
        # 计算派生属性
        vars_: dict[str, str] = {}
        for name, computed in self._data.computed.items():
            dep_value = drawn.get(computed.depends_on, "")
            vars_[name] = computed.mapping.get(dep_value or "", computed.default)

        # 把抽取结果中非 None 的值合并进来
        for name, value in drawn.items():
            if value is not None:
                vars_[name] = value

        # 用 format_map 渲染主模板，缺失的 key 渲染为空字符串
        text = self._data.template.format_map(_DefaultDict(vars_))

        # 处理后缀规则
        for rule in self._data.suffix_rules:
            # condition 格式类似 "{racial_feature}"，提取其中引用的变量名
            ref_names = re.findall(r"\{(\w+)\}", rule.condition)
            if all(vars_.get(n) for n in ref_names):
                text += rule.text.format_map(_DefaultDict(vars_))

        return text


class _DefaultDict(dict):
    """format_map 的辅助类：未找到的 key 返回空字符串"""

    def __missing__(self, key: str) -> str:
        return ""
