from typing import TypedDict

from pydantic import BaseModel, AnyUrl


class NLConfig(BaseModel):
    # 对接由 nkxingxh/yolox-onnx-api-server 启动的图像识别服务
    api: str | None = "http://127.0.0.1:9656/predict"
    api_key: str | None = None
    score_threshold: float = 0.8
    banned_emoji_package_ids: list[int] = [
        231182,
        231412,
        231764,
        239439,
        239546,
        239871,
    ]
    not_nlimg_hashes: list[str] = []  # sha256
    nlimg_hashes: list[str] = []  # sha256
    imgrec_expires: float = 60 * 60 * 12
    role_cache_expires: float = 60 * 5
    del_succ_msgs: list[str] = [
        "你不许发乃龙",
        "切莫相信乃龙，我将为你指明道路",
        "本群禁止发乃龙",
    ]
    del_fail_msgs: list[str] = [
        "😅",
        "我请问呢",
    ]
    show_score: bool = True


class ImgRec(TypedDict):
    hash: str
    sender: int
    msgid: int
    ts: float


class PredictResultEntity(TypedDict):
    box: list[float]
    class_id: int
    class_name: str
    score: float


class PredictResult(BaseModel):
    data: list[PredictResultEntity]
    et: float
    vis: None | AnyUrl
