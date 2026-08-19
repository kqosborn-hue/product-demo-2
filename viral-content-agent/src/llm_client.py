"""LLM 客户端（OpenAI 兼容 /chat/completions）。

设计要点：
- Key 缺失时 `available == False`，analyzer / creator 自动降级为规则引擎，
  Demo 永远不会因为没有 Key 而跑不起来；
- chat_json() 内置 markdown 代码块剥离与花括号截取，容忍模型输出脏数据；
- 任何异常都被封装为 LLMError，由调用方决定降级策略。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from config.settings import Settings
from .utils.http import HttpError, post_json


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def available(self) -> bool:
        return self.settings.llm_enabled

    @property
    def label(self) -> str:
        return f"{self.settings.llm_model}" if self.available else "规则引擎（未配置 LLM_API_KEY）"

    def chat(self, messages: List[Dict[str, str]], temperature: Optional[float] = None,
             json_mode: bool = False) -> str:
        if not self.available:
            raise LLMError("LLM 未配置（缺少 LLM_API_KEY / LLM_BASE_URL）")
        payload: Dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        try:
            data = post_json(url, payload,
                             headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                             timeout=self.settings.llm_timeout)
        except HttpError as exc:
            raise LLMError(str(exc)) from exc
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"响应结构异常: {str(data)[:200]}") from exc

    def chat_json(self, system: str, user: str, temperature: Optional[float] = None) -> dict:
        raw = self.chat([{"role": "system", "content": system},
                         {"role": "user", "content": user}],
                        temperature=temperature, json_mode=True)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> dict:
    """容错 JSON 解析：剥离 ```json 包裹、截取首个完整对象。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception as exc:
            raise LLMError(f"无法解析模型输出为 JSON：{text[:200]}") from exc
    raise LLMError(f"无法解析模型输出为 JSON：{text[:200]}")
