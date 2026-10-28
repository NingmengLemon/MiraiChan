# mbplugin_provenance

引用一条带图片的消息, 调用 OpenAI 的 `POST /v1/content_provenance_checks` 检查图片里有没有
C2PA 清单或 SynthID 水印, 把每张图的结果与总体结论回给用户。

接口文档: <https://developers.openai.com/api/docs/guides/content-provenance>

## 用法

- 回复一条带图片的消息, 发送 `.check` (`check_command` 可改)
- 请求被接受时在指令消息上贴一个表情回应 (`ack_reaction`, 默认 `128077` 即竖大拇指),
  表示"已收到, 正在处理"; 协议端不支持或贴失败时退回文字"正在检查 N 张图片..."
- 一次最多核验 `max_images` 张
- 默认只给 owner 与管理员用; `allow_all` 打开后所有群成员都能用, 默认关
- 同图去重按图片内容摘要判断: `image_cache_ttl` 秒内查过的图直接复用结果, 正在检查的图跳过,
  不会再为同一张图重复请求接口
- `user_cooldown` 秒内同一用户再发会被拒绝, owner 不受这条冷却限制

表情回应走 OneBot 扩展 action `set_msg_emoji_like` (SnowLuma 已支持); `ack_reaction` 置空字符串
可关掉回应, 回到纯文字回执。

开放给普通用户等于把这笔接口开销交给全群, 打开前先确认额度; 冷却对普通用户仍然生效,
owner 豁免, 缓存与并发上限 (`_gate`, 同时 2 个请求) 也对所有人一致。

`check_command` 写进配置文件之后, 改默认值不会覆盖已有配置: 老实例如果保留着旧值,
指令会按配置里的名字注册, 需要把 `configs/mbplugin_provenance/default.json` 里的
`check_command` 一起改掉再重启。

## 凭据

API key 不进插件配置, 走凭据存储:

- `credentials.json` 的 `refs` 里加 `"provenance.api_key": "..."`, 或
- 环境变量 `MIRAICHAN_PROVENANCE_API_KEY`

没配置时指令会直接提示管理员补上。

## 网络

服务器不能直连 `api.openai.com` 时, 在 `configs/mbplugin_provenance/default.json` 里把
`api_proxy` 指向可用的 HTTP 代理 (只影响核验请求, 不影响下载图片和 QQ 连接):

```json
{
    "api_proxy": "http://172.16.40.20:17890"
}
```

## 结果怎么读

- `C2PA 清单: 检测到 (签发方=..., 模型=..., 校验=trusted)`: 文件里的签名元数据可信且写着
  是 OpenAI 生成的
- `SynthID: 检测到 (模型=...)`: 文件本身带着水印, 可能扛过一些编辑
- 两项都是 `未检测到` 时, 接口只说明没找到 OpenAI 支持的信号; 元数据被抹掉、水印被破坏或者
  是别家模型生成时也是这个结果
