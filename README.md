# Mirai 酱

## 介绍

一个简单的 Bot, 使用 [melobot](https://github.com/Meloland/melobot) 作为框架

> melobot 是一个小巧可爱而强大的机器人开发框架，快去给*她*点点 star 吧！

> 名字来自于最初使用的实现端 [mirai](https://github.com/mamoe/mirai) ~~, 不会起名导致的~~,  
> 准确地说是 [Ariadne](https://github.com/GraiaProject/Ariadne) 及其系列生态库. 不过都是过去的事了uwu

在 Python 3.12 下编写/测试/运行, 其他版本尚未经测试

## 功能

> 绝赞重构中, plz wait...

## 写给自己看的

### 仓库结构

目前仓库采用 monorepo 组织形式:

- Mirai酱 主包: [`packages/miraichan`](packages/miraichan)
- 共享库: [`packages/shared/*`](packages/shared)
- 插件: [`packages/plugins/*`](packages/plugins)

### 开发说明

请使用 [uv](https://docs.astral.sh/uv/) 作为项目管理工具

最好不要将Mirai酱的主包作为依赖包安装, 推荐直接 clone 整个仓库使用

要单独使用某个共享包作为其他项目依赖的话可以:

```bash
uv add "git+https://github.com/NingmengLemon/MiraiChan.git#subdirectory=packages/shared/<package_name>"
```

(把 `<package_name>` 替换为实际的包名)

这个写法是通用的, 理论上用 pip 也能行. 但是谁会拒绝 uv 呢 uwu

或者在 `pyproject.toml` 中:

```toml
# 也记得在 project.dependencies 里加上
[tool.uv.sources]
"<package_name>" = { git = "https://github.com/NingmengLemon/MiraiChan.git", subdirectory = "packages/shared/<package_name>" }
```

## 开源相关

此项目自 [`d0be68b`](https://github.com/NingmengLemon/MiraiChan/commit/d0be68bebc31db318d62b7a59e995d9a8fbe0f3e) 及以后在 `AGPL3` 协议下开源

借鉴/参考/修改了以下项目的部分/全部源代码, 许可证与其均兼容.

- [`melobot`](https://github.com/Meloland/melobot)
- [`Python-Pinyin-Kana`](https://github.com/RUI-LONG/Python-Pinyin-Kana)

> 感谢你们为开源社区做出的贡献 ～(∠・ω< )⌒☆
