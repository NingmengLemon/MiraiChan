import json
import random
import time
from typing import NotRequired, TypedDict


class MoeData(TypedDict):
    age: str
    shallowchara: str
    deepchara: str
    habit: str
    hairstyle: NotRequired[str]
    haircolor: str
    pupilcolor: str
    breast: str
    race: str
    # 细节属性
    racial_feature: NotRequired[str]
    detailed_race: NotRequired[str]
    detailed_pupilcolor: NotRequired[str]
    # 记录时间
    time: float


class MoeLot:
    def __init__(self, moefile: str):
        with open(moefile, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        self._moeattrs: dict[str, float] = data["moeattrs"]
        self._d_moeattrs: dict[str, dict[str, float]] = data["detailed_moeattrs"]

    @staticmethod
    def random_with_weight(data_dict: dict[str, float]):
        sum_wt = sum(data_dict.values())
        ra_wt = random.uniform(0, sum_wt)
        cur_wt = 0
        for key in data_dict.keys():
            cur_wt += data_dict[key]
            if ra_wt <= cur_wt:
                return key

    def draw(self) -> MoeData:
        res = {}
        for attr_type in self._moeattrs.keys():
            res[attr_type] = self.random_with_weight(self._moeattrs[attr_type])
        for attr_type in self._d_moeattrs.keys():
            for req_attr in self._d_moeattrs[attr_type].keys():
                if req_attr in res.values():
                    res[attr_type] = self.random_with_weight(
                        self._d_moeattrs[attr_type][req_attr]
                    )
        for k in [k for k, v in res.items() if v in ("普通", "/", "无")]:
            res.pop(k)
        res["time"] = time.time()
        return res

    @staticmethod
    def to_text(moedata: MoeData):
        quantifier = "个"
        match moedata["age"]:
            case "幼女" | "萝莉" | "合法萝莉":
                quantifier = "只"
            case "少女" | "御姐" | "非法御姐":
                quantifier = "位"
        text = "一{quantifier}表面{shallowchara}、内里{deepchara}还带点{habit}的{haircolor}{pupilcolor}{breast}{race}{age}".format(
            quantifier=quantifier, **moedata
        )
        if "racial_feature" in moedata:
            text += f"，有着{moedata['racial_feature']}"
        if "detailed_race" in moedata:
            text += f"，具体地说是一{quantifier}{moedata['detailed_race']}"

        return text
