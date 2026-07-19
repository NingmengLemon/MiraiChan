import json
from importlib import resources
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import json5
from aiohttp import ClientSession
from lemony_network.request import HTTP_HEADERS
from pydantic import TypeAdapter

LOCATION_DATA_URL = "https://www.cneb.gov.cn/2021csy/js/addressDPage.js"


class Region(TypedDict):
    code: str
    name: str
    children: NotRequired[list["Region"]]


class RegionTree(TypedDict):
    name: str
    children: list[Region]


async def fetch_location_data(client: ClientSession) -> RegionTree:
    async with client.get(LOCATION_DATA_URL, headers=HTTP_HEADERS) as response:
        data = await response.text()
    return assemble_location_data((parse_js_obj(data)))


def update_local_cache(data: RegionTree):
    # Implementation for updating local cache
    with open(
        Path(__file__).parent / "location_cache.json", "w", encoding="utf-8"
    ) as fp:
        json.dump(data, fp)


region_tree_adapter = TypeAdapter(RegionTree)


def parse_js_obj(raw: str):
    # 提取 { ... } 之间的内容（从第一个 { 到最后一个 }）
    start = raw.index("{")
    # 从末尾倒数，找到匹配的 }
    depth = 0
    end = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    js_literal = raw[start:end]
    return json5.loads(js_literal)


def normalize(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    输入原始 dict（key 如 _11，value 含 name/children）
    输出规范化列表，每个元素: { code, name, children? }
    """

    result: list[dict[str, Any]] = []

    for raw_code, raw_node in data.items():
        code = raw_code.lstrip("_")  # "_11" → "11"
        name: str = raw_node["name"]
        raw_children: dict = raw_node.get("children", {})

        # 台湾数据有格式错误 —— 部分条目里嵌了平级条目
        # 例如 _7125 的 children 里同时有 _712500 和 _7126
        # 把看起来像平级 code（长度不同）的条目分离出来单独追加
        clean_children: dict[str, Any] = {}
        extra_siblings: dict[str, Any] = {}

        for k, v in raw_children.items():
            # 正常情况：子节点 code 比父节点长 2~4 位
            if len(k.lstrip("_")) > len(code):
                clean_children[k] = v
            else:
                extra_siblings[k] = v

        # 递归处理干净的 children
        children = normalize(clean_children) if clean_children else []

        # 把异常平级条目也规范化后加入结果
        if extra_siblings:
            result.extend(normalize(extra_siblings))

        # ── 处理 name 为 "-" 的虚拟节点 ──
        if name == "-":
            if children:
                # 有子节点 → 提升子节点，跳过本层
                result.extend(children)
            # 无子节点 → 直接丢弃（如东莞的 _441900: {name:"-"}）
            continue

        node: dict[str, Any] = {"code": code, "name": name}
        if children:
            node["children"] = children
        result.append(node)

    return result


def assemble_location_data(data: dict[str, Any]) -> RegionTree:
    china_children = normalize(data.get("_1", {}).get("children", {}))
    output = {
        "name": data["_1"]["name"],  # "中国"
        "children": china_children,
    }
    return region_tree_adapter.validate_python(output)
