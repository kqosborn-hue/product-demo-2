"""其他免密钥的真实公开数据源：Reddit（英文）、V2EX（中文）。

两者都是公开只读接口，不需要 API Key；Reddit 有较强风控，
失败时上层会自动切换通道（不会中断整条工作流）。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List

from ..models import Metrics, Post
from ..utils.http import get_json
from .base import AccountRef, BaseProvider, ProviderUnavailable


class RedditProvider(BaseProvider):
    name = "reddit-public-json"
    platform_support = ("reddit",)
    keyless = True

    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        if ref.kind in ("subreddit",) or ref.value.startswith("r/"):
            sub = ref.value[2:] if ref.value.startswith("r/") else ref.value
            url = f"https://www.reddit.com/r/{sub}/new.json"
        else:
            url = f"https://www.reddit.com/user/{ref.value}/submitted.json"
        params = {"limit": min(limit, 100), "raw_json": 1}
        data = get_json(url, params=params, timeout=self.settings.http_timeout,
                        headers={"Accept": "application/json"})
        self.source_urls.append(url)
        children = (data.get("data") or {}).get("children") or []
        cutoff = time.time() - days * 86400
        posts: List[Post] = []
        for ch in children:
            d = ch.get("data") or {}
            created = d.get("created_utc") or 0
            if created < cutoff:
                continue
            text = ((d.get("title") or "") + ("\n\n" + d.get("selftext") if d.get("selftext") else "")).strip()
            if not text:
                continue
            posts.append(Post(
                id=f"rd-{d.get('id')}",
                account=ref.display,
                platform="reddit",
                url="https://www.reddit.com" + (d.get("permalink") or ""),
                published_at=datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
                text=text,
                metrics=Metrics(likes=d.get("score"), comments=d.get("num_comments"),
                                reposts=d.get("num_crossposts"), collects=None,
                                views=d.get("view_count")),
                media_type="image" if d.get("post_hint") == "image" else (
                    "video" if d.get("is_video") else ("link" if not d.get("is_self") else "text")),
                source=self.name,
                raw={"subreddit": d.get("subreddit"), "author": d.get("author"),
                     "upvote_ratio": d.get("upvote_ratio")},
            ))
        if not posts:
            raise ProviderUnavailable(f"Reddit 最近 {days} 天无公开内容或被风控拦截")
        self._note("互动指标口径：score≈净赞，num_comments≈评论，num_crossposts≈转发")
        return posts


class V2exProvider(BaseProvider):
    """V2EX 公开 API：中文语料，replies 为真实回复数。"""

    name = "v2ex-public-api"
    platform_support = ("v2ex",)
    keyless = True

    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        endpoint = ("https://www.v2ex.com/api/topics/hot.json" if ref.kind == "hot"
                    else "https://www.v2ex.com/api/topics/latest.json")
        data = get_json(endpoint, timeout=self.settings.http_timeout)
        self.source_urls.append(endpoint)
        cutoff = time.time() - days * 86400
        posts: List[Post] = []
        for t in data if isinstance(data, list) else []:
            created = t.get("created") or 0
            if created < cutoff:
                continue
            title = (t.get("title") or "").strip()
            content = (t.get("content") or "").strip()
            text = title if not content else f"{title}\n\n{content}"
            if not text:
                continue
            posts.append(Post(
                id=f"v2-{t.get('id')}",
                account=ref.display,
                platform="v2ex",
                url=t.get("url") or f"https://www.v2ex.com/t/{t.get('id')}",
                published_at=datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
                text=text,
                metrics=Metrics(likes=None, comments=t.get("replies"), reposts=None,
                                collects=None, views=None),
                media_type="text",
                source=self.name,
                raw={"node": (t.get("node") or {}).get("title"),
                     "member": (t.get("member") or {}).get("username")},
            ))
        if len(posts) < 4:
            raise ProviderUnavailable("V2EX 返回样本不足（<4 条），无法做高低对比")
        self._note("互动指标口径：replies≈评论；V2EX 公开接口无赞/转发字段，已标注数据不可得")
        return posts
