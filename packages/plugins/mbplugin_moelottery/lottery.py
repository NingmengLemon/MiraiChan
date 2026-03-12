import random
import time
from importlib import resources

import json5
from melobot.log import get_logger

from . import resources as res_module
from .typedefs import (
    DetailedMoeAttrs,
    LotResult,
    LotWeight,
    MoeAttrs,
    moedata_adapter,
)

logger = get_logger()


def random_with_weight(data_dict: dict[str, LotWeight]) -> str | None:
    sum_wt = sum(data_dict.values())
    ra_wt = random.uniform(0, sum_wt)
    cur_wt = 0.0
    for key in data_dict.keys():
        cur_wt += data_dict[key]
        if ra_wt <= cur_wt:
            return key


class LotteryBox:
    def __init__(self, moefile: str | None = None) -> None:
        (
            self._moeattrs,
            self._d_moeattrs,
            self._nottomention_sentinels,
        ) = self.load_moeattrs(moefile)

    @staticmethod
    def load_moeattrs(
        moefile: str | None = None,
    ) -> tuple[MoeAttrs, DetailedMoeAttrs, set[str]]:
        if moefile is None:
            rawdata = (resources.files(res_module) / "moe_attrs.json").read_text(
                encoding="utf-8"
            )
            data = moedata_adapter.validate_python(json5.loads(rawdata))
        else:
            with open(moefile, "r", encoding="utf-8") as fp:
                data = moedata_adapter.validate_python(json5.load(fp))
        return (
            data["moeattrs"],
            data["detailed_moeattrs"],
            set(data["nottomention_sentinels"]),
        )

    def lot(self) -> LotResult:
        res = {}
        for attr_type in self._moeattrs.keys():
            res[attr_type] = random_with_weight(self._moeattrs[attr_type])

        for attr_type in self._d_moeattrs.keys():
            for req_attr in self._d_moeattrs[attr_type].keys():
                res[attr_type] = (
                    random_with_weight(self._d_moeattrs[attr_type][req_attr])
                    if req_attr in res.values()
                    else None
                )

        res = {
            k: (v if v not in self._nottomention_sentinels else None)
            for k, v in res.items()
        }
        res["time"] = time.time()
        logger.debug(f"抽取结果: {res}")
        return LotResult.model_validate(res)

    @staticmethod
    def build_response_text(moedata: LotResult):
        quantifier = "个"
        match moedata.age:
            case "幼女" | "萝莉" | "合法萝莉":
                quantifier = "只"
            case "少女" | "御姐" | "非法御姐":
                quantifier = "位"
        text = "一{quantifier}表面{shallowchara}、内里{deepchara}还带点{habit}的{haircolor}{pupilcolor}{breast}{race}{age}".format(
            quantifier=quantifier, **moedata.model_dump()
        )
        if (rf := moedata.racial_feature) is not None:
            text += f"，有着{rf}"
        if (dr := moedata.detailed_race) is not None:
            text += f"，具体地说是一{quantifier}{dr}"

        return text
