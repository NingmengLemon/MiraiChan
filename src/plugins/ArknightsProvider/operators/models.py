from typing import Literal, TypedDict

from pydantic import BaseModel


class FilterLabel(TypedDict):
    label: str
    value: list[str]


class OperatorFilterContent(TypedDict):
    title: str
    cbt: list[str | FilterLabel]
    both: bool
    field: str


class OperatorFilter(TypedDict):
    title: str
    filter: list[OperatorFilterContent]


class OperatorFilters(BaseModel):
    filters: list[OperatorFilter]


OperatorData = TypedDict(
    "Operator",
    {
        "id": str,
        "sortid": int,
        "zh": str,  # 三语姓名
        "en": str,  # 三语姓名
        "ja": str,  # 三语姓名
        "sex": str,
        "position": Literal["远程位", "近战位"],
        "tag": str,
        "profession": str,  # 职业
        "subprofession": str,  # 子职业
        "rarity": int,  # 星级
        "logo": str,  # 背后的logo
        "birth_place": str,  # 出生地
        "team": str,  # 阵营
        "race": str,  # 种族
        "obtain_method": list[str],  # 获得方式
        #
        # 数值内容
        "hp": int,  # HP
        "atk": int,  # 攻击
        "def": int,  # 防御
        "res": int,  # 法抗
        "re_deploy": int,  # 再部署
        "cost": list[int],  # 初始费用
        "block": list[int],  # 阻挡数
        "interval": float,  # 攻击间隔
        #
        # 加成
        "potential": str,  # 潜能对数值的加成
        # 格式示例 (12F)：
        # cost,atk,re_deploy,atk,cost`-1,12,-5,12,-1
        # 一共5列，按顺序从2潜到满潜，表头是加成项，对应的行是数值
        "trust": str,  # 最大信赖对数值的加成
        # 格式示例 (12F):
        # 0,50,0
        # 一共三项，生命上限 攻击 防御
        #
        # 档案内容
        "phy": str,  # 物理强度
        "flex": str,  # 战场机动
        "tolerance": str,  # 生理耐受
        "plan": str,  # 战术规划
        "skill": str,  # 战斗技巧
        "adapt": str,  # 源石技艺适应性
        "nation": str,  # 国籍
        "group": str,  # 分组（？
    },
)


class OperatorLib(BaseModel):
    data: list[OperatorData]
