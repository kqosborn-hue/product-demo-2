"""浏览器 / 网页读取通道。

两种实现：
1. JinaReaderProvider —— 免密钥，把任意公开页面转成 Markdown（r.jina.ai），
   适合服务端渲染的公开主页；对强 JS 站点（X、小红书）成功率有限。
2. PlaywrightProvider —— 真浏览器渲染，能拿到完整互动数据，
   需要 `pip install playwright && playwright install chromium`。
   已内置各平台选择器映射，登录态请通过 PLAYWRIGHT_STORAGE_STATE 注入。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import List

from ..models import Metrics, Post
from ..utils.http import get_text
from .base import AccountRef, BaseProvider, ProviderUnavailable

PROFILE_URL = {
    "x": "https://x.com/{v}",
    "weibo": "https://weibo.com/u/{v}",
    "xhs": "https://www.xiaohongshu.com/user/profile/{v}",
    "zhihu": "https://www.zhihu.com/people/{v}",
    "bilibili": "https://space.bilibili.com/{v}/dynamic",
    "hn": "https://news.ycombinator.com/submitted?id={v}",
    "v2ex": "https://www.v2ex.com/member/{v}",
}

# Playwright 选择器映射（平台改版时只需改这里）
SELECTORS = {
    "x": {"item": "article[data-testid='tweet']", "text": "div[data-testid='tweetText']",
          "time": "time", "likes": "div[data-testid='like']",
          "comments": "div[data-testid='reply']", "reposts": "div[data-testid='retweet']"},
    "weibo": {"item": "div[class*='Feed_body']", "text": "div[class*='detail_wbtext']",
              "time": "a[class*='head-info_time']", "likes": "span[class*='woo-like-count']",
              "comments": "div[class*='toolbar_item']:nth-child(2)",
              "reposts": "div[class*='toolbar_item']:nth-child(1)"},
    "xhs": {"item": "section.note-item", "text": "a.title", "time": "span.time",
            "likes": "span.count", "comments": None, "reposts": None},
}


class JinaReaderProvider(BaseProvider):
    """免密钥网页读取。把公开主页转成 Markdown 后按分隔规则切成多条内容。"""

    name = "jina-reader"
    platform_support = ("x", "weibo", "xhs", "zhihu", "bilibili", "hn", "v2ex", "url", "generic")
    keyless = True

    def _target_url(self, ref: AccountRef) -> str:
        if ref.kind == "url" or ref.value.startswith("http"):
            return ref.value
        tpl = PROFILE_URL.get(ref.platform)
        if not tpl:
            raise ProviderUnavailable(f"未知平台 {ref.platform}，请直接传入公开主页 URL")
        return tpl.format(v=ref.value.lstrip("@"))

    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        target = self._target_url(ref)
        reader = self.settings.jina_reader_base.rstrip("/") + "/" + target
        self.source_urls.append(reader)
        md = get_text(reader, timeout=max(30, self.settings.http_timeout),
                      headers={"X-Return-Format": "markdown"})
        blocks = [b.strip() for b in re.split(r"\n{2,}", md) if len(b.strip()) > 40]
        blocks = [b for b in blocks if not b.startswith(("Title:", "URL Source:", "Markdown Content:"))]
        if len(blocks) < 4:
            raise ProviderUnavailable("Jina Reader 未解析到足够内容（目标页可能强依赖 JS 或需登录）")
        posts: List[Post] = []
        now = datetime.now(timezone.utc).isoformat()
        for b in blocks[:limit]:
            pid = "jr-" + hashlib.md5(b.encode("utf-8")).hexdigest()[:10]
            posts.append(Post(
                id=pid, account=ref.display, platform=ref.platform, url=target,
                published_at=now, text=b, metrics=Metrics(), media_type="text",
                source=self.name, raw={"reader": reader},
            ))
        self._note("Jina Reader 通道无法稳定获取互动指标与准确发布时间，仅作为兜底通道；"
                   "涉及互动量对比时请改用 Playwright 通道或官方 API")
        return posts


class PlaywrightProvider(BaseProvider):
    """真浏览器渲染通道：能拿到完整的转评赞。"""

    name = "playwright-browser"
    platform_support = ("x", "weibo", "xhs", "zhihu", "bilibili", "url")
    keyless = True

    def available(self) -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except Exception:
            return False

    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        if not self.available():
            raise ProviderUnavailable("未安装 playwright：pip install playwright && playwright install chromium")
        from playwright.sync_api import sync_playwright  # type: ignore

        sel = SELECTORS.get(ref.platform)
        if not sel:
            raise ProviderUnavailable(f"{ref.platform} 暂无选择器配置，请在 SELECTORS 中补充")
        url = (ref.value if ref.value.startswith("http")
               else PROFILE_URL[ref.platform].format(v=ref.value.lstrip("@")))
        self.source_urls.append(url)
        storage = os.environ.get("PLAYWRIGHT_STORAGE_STATE") or None
        posts: List[Post] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0")
            ctx = browser.new_context(storage_state=storage) if storage else browser.new_context()
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            for _ in range(4):                      # 滚动加载更多历史内容
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            items = page.query_selector_all(sel["item"])[:limit]
            for idx, it in enumerate(items):
                text = (it.query_selector(sel["text"]).inner_text()
                        if sel.get("text") and it.query_selector(sel["text"]) else it.inner_text())
                if not text or len(text.strip()) < 10:
                    continue
                published = ""
                if sel.get("time") and it.query_selector(sel["time"]):
                    node = it.query_selector(sel["time"])
                    published = node.get_attribute("datetime") or node.inner_text() or ""
                posts.append(Post(
                    id=f"pw-{ref.platform}-{idx}", account=ref.display, platform=ref.platform,
                    url=url, published_at=published or datetime.now(timezone.utc).isoformat(),
                    text=text.strip(),
                    metrics=Metrics(likes=_num(it, sel.get("likes")),
                                    comments=_num(it, sel.get("comments")),
                                    reposts=_num(it, sel.get("reposts"))),
                    media_type="text", source=self.name, raw={},
                ))
            browser.close()
        if not posts:
            raise ProviderUnavailable("浏览器通道未解析到内容（可能需要登录态 PLAYWRIGHT_STORAGE_STATE）")
        return posts


def _num(node, selector):
    if not selector:
        return None
    try:
        el = node.query_selector(selector)
        if not el:
            return None
        raw = re.sub(r"[^\d\.万wW]", "", el.inner_text() or "")
        if not raw:
            return None
        mult = 10000 if raw[-1] in "万wW" else 1
        return int(float(re.sub(r"[万wW]", "", raw)) * mult)
    except Exception:
        return None
