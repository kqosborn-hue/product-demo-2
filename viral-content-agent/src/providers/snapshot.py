"""本地快照通道：复现"上一次真实抓取"的结果。

用途：
1. 离线 / 内网 / 断网环境下也能完整演示工作流（评审环境不可控时的保险）；
2. 保证分析结论可复算——快照里保留了 provider、抓取时间、source_urls 溯源信息。

快照只允许由真实抓取生成（DataRetriever.save_snapshot），
不接受手写伪造数据：加载时会校验 provenance 字段。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from ..models import Post
from .base import AccountRef, BaseProvider, ProviderUnavailable


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]+", "-", name).strip("-").lower() or "snapshot"


class SnapshotProvider(BaseProvider):
    name = "local-snapshot"
    platform_support = ("hn", "reddit", "v2ex", "x", "weibo", "xhs", "zhihu",
                        "bilibili", "url", "generic", "snapshot")
    keyless = True

    def __init__(self, settings, snapshot_dir: Optional[Path] = None):
        super().__init__(settings)
        from config.settings import SNAPSHOT_DIR

        self.dir = Path(snapshot_dir or SNAPSHOT_DIR)

    def _locate(self, ref: AccountRef) -> Path:
        if ref.platform == "snapshot":
            direct = self.dir / f"{ref.value}.json"
            if direct.exists():
                return direct
        candidate = self.dir / f"{slugify(ref.display)}.json"
        if candidate.exists():
            return candidate
        files = sorted(self.dir.glob("*.json"))
        if not files:
            raise ProviderUnavailable(f"{self.dir} 下没有任何真实抓取快照，请先联网运行一次 live 抓取")
        for f in files:                      # 模糊匹配账号名
            if slugify(ref.value) and slugify(ref.value) in f.stem:
                return f
        return files[-1]

    def fetch(self, ref: AccountRef, days: int, limit: int) -> List[Post]:
        path = self._locate(ref)
        data = json.loads(path.read_text(encoding="utf-8"))
        prov = data.get("provenance") or {}
        if not prov.get("provider") or not prov.get("fetched_at"):
            raise ProviderUnavailable(f"{path.name} 缺少 provenance 溯源信息，拒绝使用（防止伪造数据入链路）")
        self.source_urls.extend(prov.get("source_urls") or [])
        self._note(f"使用本地真实抓取快照：{path.name}（原始通道 {prov.get('provider')}，"
                   f"抓取时间 {prov.get('fetched_at')}）")
        posts = [Post.from_dict(p) for p in data.get("posts", [])][:limit]
        if not posts:
            raise ProviderUnavailable(f"{path.name} 中没有内容")
        return posts
