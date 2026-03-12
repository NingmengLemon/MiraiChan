from typing import TypedDict

from pydantic import TypeAdapter

type LotWeight = float | int


class MoeAttrs(TypedDict):
    age: dict[str, LotWeight]
    shallowchara: dict[str, LotWeight]
    deepchara: dict[str, LotWeight]
    habit: dict[str, LotWeight]
    hairstyle: dict[str, LotWeight]
    haircolor: dict[str, LotWeight]
    pupilcolor: dict[str, LotWeight]
    breast: dict[str, LotWeight]


moeattrs_adapter = TypeAdapter(MoeAttrs)


class DetailedMoeAttrs(TypedDict):
    racial_feature: dict[str, LotWeight]
    detailed_race: dict[str, LotWeight]
    detailed_pupilcolor: dict[str, LotWeight]


detailed_moeattrs_adapter = TypeAdapter(DetailedMoeAttrs)


class MoeData(TypedDict):
    nottomention_sentinels: list[str]
    moeattrs: MoeAttrs
    detailed_moeattrs: DetailedMoeAttrs


moedata_adapter = TypeAdapter(MoeData)


class LotResult(TypedDict):
    age: str
    shallowchara: str
    deepchara: str
    habit: str
    hairstyle: str | None
    haircolor: str
    pupilcolor: str
    breast: str
    race: str
    # 细节属性
    racial_feature: str | None
    detailed_race: str | None
    detailed_pupilcolor: str | None
    # 记录时间
    time: float


lotresult_adapter = TypeAdapter(LotResult)
