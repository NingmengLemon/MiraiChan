import asyncio
import os.path
import tempfile
import shutil
from typing import Any

from melobot import get_logger
from melobot.protocols.onebot.v11.adapter.echo import _GetGroupMemberInfoEchoData
import graphviz
import aiofiles

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers


async def fetch_avatar(uid: int, dst: str):
    try:
        url = f"http://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
        async with async_http(url, "get", headers=http_headers) as resp:
            resp.raise_for_status()
            async with aiofiles.open(dst, "wb") as fp:
                return await fp.write(await resp.content.read())
    except Exception as e:
        get_logger().warning(f"error while fetching avatar: {e}")
        return 0


async def render(
    memlist: list[_GetGroupMemberInfoEchoData],
    waifudump: list[dict[str, Any]],
    mrgdump: list[dict[str, Any]],
):
    memtable = {mem["user_id"]: mem for mem in memlist}
    users = set[int]()
    for w in waifudump:
        users.add(w["src"])
        users.add(w["dst"])
    for m in mrgdump:
        users.add(m["a"])
        users.add(m["b"])

    dot = graphviz.Digraph(
        graph_attr={
            "dpi": "150",
            "beautify": "true",
            "compound": "true",
            "ranksep": "1",
            "splines": "ortho",
        },
        format="png",
        encoding="utf-8",
    )
    tmpdir = tempfile.mkdtemp(dir="./")
    try:
        await asyncio.gather(
            *[fetch_avatar(u, os.path.join(tmpdir, f"{u}_avatar.jpg")) for u in users]
        )
        has_avatar = {
            u for u in users if os.path.isfile(os.path.join(tmpdir, f"{u}_avatar.jpg"))
        }
        for uid in users:
            uinfo = memtable.get(uid, {})
            username = uinfo.get("card") or uinfo.get("nickname", str(uid))
            dot.node(
                str(uid),
                label=(
                    username[:6] + "..." if username and len(username) > 6 else username
                ),
            )
            continue
            if uid not in has_avatar:
                continue
            # modified from kmua bot
            with dot.subgraph(name=f"cluster_{uid}") as subgraph:
                # Set the attributes for the subgraph
                subgraph.attr(label=username)
                subgraph.attr(rank="same")  # Ensure nodes are on the same rank
                subgraph.attr(labelloc="b")  # Label position at the bottom
                subgraph.attr(style="filled")
                # Create a node within the subgraph
                subgraph.node(
                    str(uid),
                    label="",
                    shape="none",
                    image=os.path.join(tmpdir, f"{uid}_avatar.jpg"),
                    imagescale="true",
                )
        for rel in waifudump:
            uid = rel["src"]
            waifu = rel["dst"]
            dot.edge(
                str(uid),
                str(waifu),
                # lhead=f"cluster_{waifu}" if waifu in has_avatar else "",
                # ltail=f"cluster_{uid}" if uid in has_avatar else "",
            )
        for rel in mrgdump:
            uid = rel["a"]
            waifu = rel["b"]
            dot.edge(
                str(uid),
                str(waifu),
                # lhead=f"cluster_{waifu}" if waifu in has_avatar else "",
                # ltail=f"cluster_{uid}" if uid in has_avatar else "",
                arrowhead="none",
            )
        get_logger().debug(f"{dot.source=}")
        return await asyncio.to_thread(dot.pipe)
        # return dot.source
    finally:
        if os.path.exists(tmpdir):
            shutil.rmtree(tmpdir)
