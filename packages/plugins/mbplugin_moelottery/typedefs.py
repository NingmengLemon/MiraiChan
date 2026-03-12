from __future__ import annotations

from pydantic import BaseModel, Field

type Weight = float | int

# ---- 资源文件中每个属性池的定义 ----


class PoolDependency(BaseModel):
    """条件依赖：当另一个池的抽取结果命中 triggers 中的某个 key 时，才从对应的选项中抽取"""

    pool: str
    triggers: dict[str, dict[str, Weight]]


class AttrPool(BaseModel):
    """一个属性池"""

    label: str
    options: dict[str, Weight] | None = None
    nullable: bool = False
    null_weight: Weight = 0
    depends_on: PoolDependency | None = None


# ---- 计算属性（由已有抽取结果派生） ----


class ComputedAttr(BaseModel):
    """根据另一个池的结果映射出一个派生值"""

    depends_on: str
    mapping: dict[str, str]
    default: str


# ---- 后缀规则 ----


class SuffixRule(BaseModel):
    """当 condition 中引用的变量有值时，追加 text 到结果末尾"""

    condition: str
    text: str


# ---- 整个资源文件的顶层结构 ----


class MoeData(BaseModel):
    template: str
    suffix_rules: list[SuffixRule] = Field(default_factory=list)
    computed: dict[str, ComputedAttr] = Field(default_factory=dict)
    pools: dict[str, AttrPool]
