"""搜索工具通道：X / 微博 / 小红书 / 抖音等需要登录的平台走搜索引擎抓公开结果。

支持 Serper(Google) / Tavily / 博查(Bocha) 三家，API Key 从 .env 读取。
互动数据能从摘要里解析就解析，解析不到一律留空（Metrics=None），
由报表标注"数据不可得"——严禁为了凑表格而编造数字。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..models import Metrics, Post
from ..utils.http import get_json, post_json
from .base import AccountRef, BaseProvider, ProviderUnavailable

SITE_MAP = {
    "x": "x.com", "weibo": "weibo.com", "xhs": "xiaohongshu.com",
    "douyin": "douyin.com", "bilibili": "bilibili.com", "zhihu": "zhihu.com",
}

_METRIC_RE = {
    "likes": re.compile(r"(\d[\d,\.]*\s*[万wW]?)\s*(?:个?赞|点赞|likes?|👍)", re.I),
    "comments": re.compile(r"(\d[\d,\.]*\s*[万wW]?)\s*(?:条?评论|回复|comments?|replies)", re.I),
    "reposts": re.compile(r"(\d[\d,\.]*\s*[万wW]?)\s*(?:转发|转推|retweets?|shares?)", re.I),
    "collects": re.compile(r"(\d[\d,\.]*\s*[万wW]?)\s*(?:收藏|saves?)", re.I),
}


def _parse_count(raw: str) -> Optional[int]:
    s = raw.replace(",", "").strip()
    mult = 1
    if s and s[-1] in "万wW":
        mult, s = 10000, s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return None


def _extract_metrics(text: str) -> Metrics:
    m = Metrics()
    for field, pattern in _METRIC_RE.items():
        hit = pattern.search(text or "")
        if hit:
            setattr(m, field, _parse_count(hit.group(1)))
    return m


class SearchApiProvider(BaseProvider):
    name = "search-api"
    platform_support = ("x", "weibo", "xhs", "douyin", "bilibili", "zhihu", "generic", "url")
    keyless = False

    def available(self) -> bool:
        s = self.settings
        return bool({"serper": s.serper_api_key, "tavily": s.tavily_api_key,
                     "bocha": s.bocha_api_key}.get(s.search_provider))

    # ------------------------------------------------------------------
    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        if not self.available():
            raise ProviderUnavailable(
                f"未配置 {self.settings.search_provider.upper()}_API_KEY，无法走搜索通道（见 .env.example）")
        site = SITE_MAP.get(ref.platform)
        target = ref.value.lstrip("@")
        query = f'site:{site} "{target}"' if site else target
        results = {
            "serper": self._serper, "tavily": self._tavily, "bocha": self._bocha,
        }[self.settings.search_provider](query, limit, days)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        posts: List[Post] = []
        for item in results:
            text = "\n".join(x for x in [item.get("title", ""), item.get("snippet", "")] if x).strip()
            if len(text) < 10:
                continue
            published = item.get("date") or ""
            dt = _loose_datetime(published)
            if dt and dt < cutoff:
                continue
            url = item.get("link", "")
            pid = "sr-" + hashlib.md5((url or text).encode("utf-8")).hexdigest()[:10]
            posts.append(Post(
                id=pid, account=ref.display, platform=ref.platform, url=url,
                published_at=(dt or datetime.now(timezone.utc)).isoformat(),
                text=text, metrics=_extract_metrics(text), media_type="text",
                source=f"{self.name}:{self.settings.search_provider}",
                raw={"date_raw": published, "engine": self.settings.search_provider},
            ))
        if not posts:
            raise ProviderUnavailable("搜索通道未返回可用的公开内容")
        self._note("搜索通道抓取的互动数据依赖摘要文本，解析不到的指标一律留空并标注'数据不可得'")
        self._note("如需完整互动数据，请配置 Playwright 浏览器通道（见 README「真实数据获取」）")
        return posts

    # ------------------------------------------------------------------
    def _serper(self, query: str, limit: int, days: int) -> List[Dict]:
        payload = {"q": query, "num": min(limit, 20), "hl": "zh-cn",
                   "tbs": f"qdr:d{max(1, days)}"}
        data = post_json("https://google.serper.dev/search", payload,
                         headers={"X-API-KEY": self.settings.serper_api_key},
                         timeout=self.settings.http_timeout)
        self.source_urls.append(f"serper:{query}")
        return data.get("organic", []) or []

    def _tavily(self, query: str, limit: int, days: int) -> List[Dict]:
        payload = {"api_key": self.settings.tavily_api_key, "query": query,
                   "max_results": min(limit, 20), "search_depth": "advanced",
                   "days": days, "topic": "news"}
        data = post_json("https://api.tavily.com/search", payload,
                         timeout=self.settings.http_timeout)
        self.source_urls.append(f"tavily:{query}")
        return [{"title": r.get("title"), "snippet": r.get("content"),
                 "link": r.get("url"), "date": r.get("published_date")}
                for r in data.get("results", [])]

    def _bocha(self, query: str, limit: int, days: int) -> List[Dict]:
        payload = {"query": query, "count": min(limit, 20), "freshness": f"oneMonth"}
        data = post_json("https://api.bochaai.com/v1/web-search", payload,
                         headers={"Authorization": f"Bearer {self.settings.bocha_api_key}"},
                         timeout=self.settings.http_timeout)
        self.source_urls.append(f"bocha:{query}")
        pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
        return [{"title": p.get("name"), "snippet": p.get("snippet"),
                 "link": p.get("url"), "date": p.get("dateLastCrawled")} for p in pages]


def _loose_datetime(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    m = re.match(r"(\d+)\s*(小时|hours?|hrs?)", raw, re.I)
    if m:
        return datetime.now(timezone.utc) - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*(天|days?)", raw, re.I)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%b %d, %Y", "%Y年%m月%d日"):
        try:
            dt = datetime.strptime(raw[:len("2026-01-01T00:00:00")], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None
