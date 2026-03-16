# nbnhhsh

> 能不能好好说话!

## API 分析

从代码中提取出以下两个可用的 API：

| API | 方法 | 路径 | 说明 |
|-----|------|------|------|
| **guess** | POST | `/api/nbnhhsh/guess` | 根据缩写猜测含义 |
| **submitTran** | POST | `/api/nbnhhsh/translation/{name}` | 提交翻译对应关系 |

---

## Python 代码实现

```python
import httpx
from pydantic import BaseModel, Field
from typing import Optional


# ============ 数据模型定义 ============

class GuessRequest(BaseModel):
    """猜测缩写的请求"""
    text: str = Field(..., description="要查询的缩写文本，多个用逗号分隔")


class TranslationItem(BaseModel):
    """翻译条目"""
    text: str = Field(..., description="翻译文本")
    sub: Optional[str] = Field(None, description="来源备注")


class GuessResponseItem(BaseModel):
    """单个缩写的猜测结果"""
    name: str = Field(..., description="缩写名称")
    trans: Optional[list[str]] = Field(None, description="已确认的翻译列表")
    inputting: Optional[list[str]] = Field(None, description="正在输入中的候选")


class SubmitTranslationRequest(BaseModel):
    """提交翻译的请求"""
    text: str = Field(..., description="缩写对应的文字，末尾可通过括号包裹注明来源")


# ============ API 客户端 ============

class NbnhhshClient:
    """能不能好好说话？ API 客户端"""
  
    BASE_URL = "https://lab.magiconch.com/api/nbnhhsh"
  
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.Client(timeout=timeout)
  
    def __enter__(self):
        return self
  
    def __exit__(self, *args):
        self._client.close()
  
    def guess(self, text: str) -> list[GuessResponseItem]:
        """
        猜测缩写的含义
      
        Args:
            text: 要查询的缩写，支持多个（用逗号分隔）
          
        Returns:
            猜测结果列表
        """
        # 预处理：只保留字母数字，2位以上
        import re
        cleaned_text = ",".join(re.findall(r"[a-z0-9]{2,}", text, flags=re.I))
      
        response = self._client.post(
            f"{self.BASE_URL}/guess",
            json={"text": cleaned_text},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
      
        data = response.json()
        return [GuessResponseItem(**item) for item in data]
  
    def submit_translation(self, abbr: str, translation: str) -> None:
        """
        提交缩写对应的翻译
      
        Args:
            abbr: 缩写名称
            translation: 翻译文本，末尾可通过括号包裹注明来源
        """
        response = self._client.post(
            f"{self.BASE_URL}/translation/{abbr}",
            json={"text": translation},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()


# ============ 使用示例 ============

if __name__ == "__main__":
    # 查询缩写含义
    with NbnhhshClient() as client:
        # 示例：查询 "xswl" 和 "yyds"
        results = client.guess("xswl,yyds")
      
        for item in results:
            print(f"缩写: {item.name}")
          
            if item.trans:
                print(f"  翻译: {', '.join(item.trans)}")
            elif item.inputting:
                print(f"  候选: {', '.join(item.inputting)}")
            else:
                print("  尚未录入")
      
        # 提交翻译（需审核通过后生效）
        # client.submit_translation("xswl", "笑死我了")
```

---

## 响应数据结构

### guess 接口返回示例

```json
[
  {
    "name": "xswl",
    "trans": ["笑死我了", "笑死算了"],
    "inputting": null
  },
  {
    "name": "yyds",
    "trans": ["永远滴神"],
    "inputting": ["永远的神", "永远单身"]
  },
  {
    "name": "emo",
    "trans": null,
    "inputting": ["我emo了", "emo了"]
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 缩写名称 |
| `trans` | string[] \| null | 已确认的翻译列表 |
| `inputting` | string[] \| null | 用户正在输入的候选翻译 |
