"""数据源抽象。

账号定位符（account locator）统一格式： `<platform>:<kind>:<value>`
    hn:author:pseudolus        Hacker News 账号主页（免密钥，真实 points / comments）
    hn:topic:AI agent         Hacker News 话题流（免密钥）
    reddit:user:spez          Reddit 用户（免密钥，可能被风控）
    reddit:r/LocalLLaMA       Reddit 版块（免密钥，可能被风控）
    v2ex:latest               V2EX 最新主题（免密钥，中文语料）
    x:@handle / weibo:uid / xhs:userid / url:https://...
                              → 走搜索 API 或 Jina Reader / Playwright 通道
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..models import Post


@dataclass
class AccountRef:
    raw: str
    platform: str
    kind: str
    value: str

    @property
    def display(self) -> str:
        return f"{self.platform}:{self.kind}:{self.value}" if self.kind else f"{self.platform}:{self.value}"


_KNOWN = {"hn", "hackernews", "reddit", "v2ex", "x", "twitter", "weibo", "xhs",
          "xiaohongshu", "douyin", "bilibili", "zhihu", "url", "snapshot"}


def parse_account(raw: str) -> AccountRef:
    """把用户输入的"账号链接/名称"解析为统一引用。"""
    s = (raw or "").strip()
    if s.startswith("http://") or s.startswith("https://"):
        host = re.sub(r"^www\.", "", s.split("/")[2].lower())
        platform = {
            "x.com": "x", "twitter.com": "x", "weibo.com": "weibo",
            "xiaohongshu.com": "xhs", "zhihu.com": "zhihu",
            "news.ycombinator.com": "hn", "reddit.com": "reddit", "v2ex.com": "v2ex",
        }.get(host, "url")
        return AccountRef(raw=s, platform=platform, kind="url", value=s)

    parts = s.split(":", 2)
    head = parts[0].lower()
    if head in _KNOWN:
        platform = "hn" if head == "hackernews" else ("x" if head == "twitter" else head)
        platform = "xhs" if platform == "xiaohongshu" else platform
        if len(parts) == 3:
            return AccountRef(raw=s, platform=platform, kind=parts[1].lower(), value=parts[2].strip())
        if len(parts) == 2:
            v = parts[1].strip()
            kind = "subreddit" if v.startswith("r/") else ("author" if platform == "hn" else "user")
            if platform == "v2ex" and v in ("latest", "hot"):
                kind = v
                v = v
            return AccountRef(raw=s, platform=platform, kind=kind, value=v)
    if s.startswith("@"):
        return AccountRef(raw=s, platform="x", kind="user", value=s[1:])
    return AccountRef(raw=s, platform="generic", kind="name", value=s)


class BaseProvider(ABC):
    """数据源统一接口。"""

    name: str = "base"
    platform_support: Tuple[str, ...] = ()
    keyless: bool = True

    def __init__(self, settings):
        self.settings = settings
        self.source_urls: List[str] = []
        self.notes: List[str] = []

    def supports(self, ref: AccountRef) -> bool:
        return ref.platform in self.platform_support

    def available(self) -> bool:
        return True

    @abstractmethod
    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        """抓取近 N 天的公开内容。抓不到应抛异常，由上层切换通道。"""

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


class ProviderUnavailable(RuntimeError):
    pass
