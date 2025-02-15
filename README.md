# Mirai 酱

## 介绍

一个简单的 Bot, 使用 [melobot](https://github.com/Meloland/melobot) 作为框架

> melobot 是一个小巧可爱而强大的机器人开发框架，快去给她点点 star 吧！

名字来自于最初基于的实现端 mirai ~~, 不会起名导致的~~, 现在已经是第四次重写惹qwq

## 功能

目前规划了下面的功能，勾选的是已经基本完成的：

- [ ] 复读机 ~~，计划中是贴近 [`Pallas-Bot`](https://github.com/MistEO/Pallas-Bot) 中的那种?~~
- [ ] `Executor` 交互式 shell 和 Python 代码执行
- [x] `NoNailong` 反奶龙图像识别
  > 模型使用 [`NailongDetection`](https://github.com/nkxingxh/NailongDetection)，识别服务部署使用 [`yolox-onnx-api-server`](https://github.com/nkxingxh/yolox-onnx-api-server)
- [ ] `Pooooke` 戳！（戳一戳相关玩法）
- [x] `EroMoncak` 不许涩涩！（特化的关键字回复）
- [ ] `BiliLinkPurify` B站分享链接脱敏与预览
- [x] `WhatToListenToday` 今天听什么（关联仓库见 [miraichan-music-lottery](https://github.com/NingmengLemon/miraichan-music-lottery)） ~~已经变成点歌台了~~
- [ ] `WhatToEatToday` 今天吃什么
- [ ] 自动群管理员
- [ ] 通用的关键字/正则回复
- [ ] 交互式权限系统
- [x] `JustQuote` 群U骚话存档
- [x] `MomoQuote` 产出图像更美观的群U骚话存档 ~~用pillow嗯拼的, 是史, 别看源码~~
- [ ] `DailyWaifu` 每日群U老婆
- [ ] `ArknightsUtils` 明日方舟相关小工具

\* 计划仍在绝赞追加中，但是进度嘛，就……（逃

## 开源相关

此项目自 [`d0be68b`](https://github.com/NingmengLemon/MiraiChan/commit/d0be68bebc31db318d62b7a59e995d9a8fbe0f3e) 及以后在 `AGPL3` 协议下开源发行

借鉴/参考/修改了以下项目的部分/全部源代码, 许可证与其均兼容.

- [`melobot`](https://github.com/Meloland/melobot)
- [`Python-Pinyin-Kana`](https://github.com/RUI-LONG/Python-Pinyin-Kana)

> 感谢你们为开源社区做出的贡献 ～(∠・ω< )⌒☆
