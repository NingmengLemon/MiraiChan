# mbplugin_provenance

引用一条带图片的消息, 调用 OpenAI 的 `POST /v1/content_provenance_checks` 检查图片里有没有
C2PA 清单或 SynthID 水印, 把每张图的结果与总体结论回给用户。

接口文档: <https://developers.openai.com/api/docs/guides/content-provenance>

## 用法

- 回复一条带图片的消息, 发送 `.核验` (`check_command` 可改)
- 一次最多核验 `max_images` 张, 默认只给 owner 与管理员用 (`allow_admins`)

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
