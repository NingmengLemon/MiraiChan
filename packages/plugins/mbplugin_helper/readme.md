# mbplugin_helper

`.help` / `.帮助` 列出所有功能, `.help <名称>` 只看某一项。内容以合并转发发送, 一个插件
(或一条指令) 一个节点; 协议端发送合并转发失败时退回普通消息。

## 给插件加帮助

在插件的 `__plugin__.py` 模块级注册, 依赖 `lemony_utils`:

```python
from lemony_utils.help import Command, register_help

register_help(
    PLUGIN_IDENTIFIER,
    title="引用图",
    summary="把群消息画成图片",
    aliases=["quote"],
    commands=[
        Command(".q", "回复一条消息, 生成名言卡片"),
        Command(".qdel", "回复 bot 发出的引用图, 删除存档", admin_only=True),
    ],
)
```

只有已加载的插件会出现在帮助里。展示顺序是插件的加载顺序。
