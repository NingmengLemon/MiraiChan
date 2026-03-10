import json
from os import PathLike

from pypinyin import Style, pinyin

PY2KTKN_MAP: dict[str, str] = {}


def load_py2ktkn_map(data_path: PathLike | str = "data/pinyin2ktkn.json") -> None:
    global PY2KTKN_MAP
    # https://github.com/RUI-LONG/Python-Pinyin-Kana/blob/70f93061786ce538a2b26798e67fa501fd9b9867/pinyin_kana/pinyin_dicts.py#L40
    with open(data_path, "r", encoding="utf-8") as fp:
        PY2KTKN_MAP = json.load(fp)


def _convert_to_katakana(text, ignore_non_kana=False):
    pinyin_list = [
        "".join(char for char in word[0])
        for word in pinyin(text, style=Style.NORMAL, heteronym=False)
    ]
    if ignore_non_kana:
        return [PY2KTKN_MAP.get(p, "") for p in pinyin_list]
    return [PY2KTKN_MAP.get(p, p) for p in pinyin_list]


def pinyin_to_katakana(text: str | list[str]) -> list[str]:
    if not PY2KTKN_MAP:
        load_py2ktkn_map()
    if isinstance(text, list):
        return ["".join(_convert_to_katakana(t)) for t in text]
    return _convert_to_katakana(text)


if __name__ == "__main__":
    load_py2ktkn_map()
    chinese_text = "你好ww,, wq我叫ww"
    katakana_text = pinyin_to_katakana(chinese_text)
    print("原文:", chinese_text)
    print("片假名:", katakana_text)
