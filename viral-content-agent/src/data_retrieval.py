"""第一步：真实数据获取与筛选（模块化职责一：数据获取）。

对外只暴露一个入口 `DataRetriever.retrieve()`，内部完成：
    1. 解析"账号链接/名称" → AccountRef
    2. 按优先级串行尝试各真实数据通道（失败自动降级，全部失败回落本地真实快照）
    3. 30 天窗口过滤（样本不足时自动扩窗并在报表中显式标注）
    4. 分类：Top 1-3 高表现内容 + 2-3 条普通内容对照组
    5. 保存快照，保证结论可复算
"""

from __future__ import annotations

import json
import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from config.settings import SNAPSHOT_DIR, Settings
from .models import Dataset, Post
from .providers import (LIVE_PROVIDERS, AccountRef, ProviderUnavailable,
                        SnapshotProvider, parse_account, slugify)


class DataRetriever:
    def __init__(self, settings: Settings, logger: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.log = logger or (lambda msg: None)

    # ------------------------------------------------------------------ 主流程
    def retrieve(self, account: str, days: Optional[int] = None,
                 limit: Optional[int] = None, source: Optional[str] = None) -> Dataset:
        days = days or self.settings.lookback_days
        limit = limit or self.settings.fetch_limit
        source = (source or self.settings.data_source).lower()
        ref = parse_account(account)
        self.log(f"账号定位符解析：{ref.raw} → 平台={ref.platform} 维度={ref.kind} 目标={ref.value}")

        posts, provider_name, source_urls, notes = self._fetch_with_fallback(ref, days, limit, source)

        window_posts, window_note = self._filter_window(posts, days)
        if window_note:
            notes.append(window_note)

        dataset = Dataset(
            account=ref.display, platform=ref.platform, window_days=days,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            provider=provider_name, source_urls=source_urls,
            posts=window_posts, notes=notes,
        )
        dataset.high_performers, dataset.control_group = self.classify(window_posts)
        return dataset

    # ------------------------------------------------------------------ 通道选择
    def _fetch_with_fallback(self, ref: AccountRef, days: int, limit: int,
                             source: str) -> Tuple[List[Post], str, List[str], List[str]]:
        notes: List[str] = []
        if source == "snapshot":
            p = SnapshotProvider(self.settings)
            posts = p.fetch(ref, days, limit)
            return posts, p.name, p.source_urls, list(p.notes)

        errors: List[str] = []
        for cls in LIVE_PROVIDERS:
            provider = cls(self.settings)
            if not provider.supports(ref):
                continue
            if not provider.available():
                errors.append(f"{provider.name}: 未就绪（缺少依赖或 API Key）")
                self.log(f"跳过通道 {provider.name}（未就绪）")
                continue
            try:
                self.log(f"尝试真实数据通道：{provider.name}")
                posts = provider.fetch(ref, days, limit)
                self.log(f"通道 {provider.name} 命中，返回 {len(posts)} 条公开内容")
                notes.extend(provider.notes)
                return posts, provider.name, provider.source_urls, notes
            except Exception as exc:                       # 通道失败 → 降级下一个
                errors.append(f"{provider.name}: {exc}")
                self.log(f"通道 {provider.name} 失败：{exc}")

        if source == "live":
            raise ProviderUnavailable("所有实时通道均失败：\n  - " + "\n  - ".join(errors))

        self.log("所有实时通道失败，回落到本地真实抓取快照")
        p = SnapshotProvider(self.settings)
        posts = p.fetch(ref, days, limit)
        notes.append("实时通道不可用，本次使用历史真实抓取快照；失败原因：" + "；".join(errors[:3]))
        notes.extend(p.notes)
        return posts, p.name, p.source_urls, notes

    # ------------------------------------------------------------------ 时间窗
    def _filter_window(self, posts: List[Post], days: int) -> Tuple[List[Post], str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        inside, outside = [], []
        for p in posts:
            dt = p.published_dt
            if dt is None:
                outside.append(p)
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            (inside if dt >= cutoff else outside).append(p)
        if len(inside) >= 5:
            return inside, ""
        merged = inside + outside
        note = (f"最近 {days} 天内仅取到 {len(inside)} 条样本，不足以支撑对比，"
                f"已自动扩展样本至 {len(merged)} 条（含窗口外内容），请在解读结论时注意这一点")
        return merged, note

    # ------------------------------------------------------------------ 分类
    def classify(self, posts: List[Post]) -> Tuple[List[Post], List[Post]]:
        """筛出高表现内容（Top 1-3）与普通内容对照组（2-3 条）。

        规则（可复现）：
        - 排序键：优先互动率（有曝光数据时），否则互动总量
        - 高表现：Top N，且必须显著高于中位数（>= 1.5x），避免"矮子里拔将军"
        - 普通组：排除 Top 20% 后，在中位数附近的样本里用固定随机种子抽样
        """
        scored = [(self._score(p), p) for p in posts if p.text]
        scored.sort(key=lambda x: x[0], reverse=True)
        if len(scored) < 3:
            return [p for _, p in scored[:1]], [p for _, p in scored[1:]]

        values = [s for s, _ in scored]
        median = statistics.median(values) or 0.0
        top_n = self.settings.top_high_performers

        high: List[Post] = []
        for score, post in scored[:top_n]:
            if not high or score >= median * 1.5 or median == 0:
                high.append(post)
        if not high:
            high = [scored[0][1]]

        cut = max(len(high), int(len(scored) * 0.2))
        pool = [p for _, p in scored[cut:]]
        # 取中间段（去掉极端零互动），更能代表"普通内容"
        if len(pool) > 6:
            mid_start = len(pool) // 4
            pool = pool[mid_start: mid_start + max(4, len(pool) // 2)]
        rng = random.Random(self.settings.random_seed)
        k = min(self.settings.control_group_size, len(pool))
        control = rng.sample(pool, k) if k > 0 else []
        return high, control

    def _score(self, post: Post) -> float:
        rate = post.metrics.engagement_rate
        return float(rate) if rate is not None else float(post.metrics.total)

    # ------------------------------------------------------------------ 快照
    def save_snapshot(self, dataset: Dataset, snapshot_dir: Optional[Path] = None) -> Path:
        d = Path(snapshot_dir or SNAPSHOT_DIR)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{slugify(dataset.account)}.json"
        payload = {
            "provenance": {
                "provider": dataset.provider,
                "fetched_at": dataset.fetched_at,
                "account": dataset.account,
                "platform": dataset.platform,
                "window_days": dataset.window_days,
                "source_urls": dataset.source_urls,
                "notes": dataset.notes,
                "disclaimer": "本文件由真实公开接口抓取生成，未经人工编辑；互动数字为平台原始值。",
            },
            "posts": [p.to_dict() for p in dataset.posts],
            "high_performer_ids": [p.id for p in dataset.high_performers],
            "control_group_ids": [p.id for p in dataset.control_group],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
