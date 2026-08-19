"""测试公共夹具：构造最小可复用的领域对象，避免测试依赖网络。

所有夹具只使用标准库与项目内纯函数，保证在无 LLM Key、无外网的环境下
也能完整跑通（与"真实快照离线演示"的设计一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone, timedelta

import pytest

from config.settings import get_settings
from src.models import (AnalysisResult, Dataset, Draft, Metrics, Post,
                        ViralTemplate)


def _utc(days_ago: int = 0, hour: int = 10) -> str:
    base = datetime(2026, 8, 1, hour, 0, tzinfo=timezone.utc)
    return (base - timedelta(days=days_ago)).isoformat()


def make_post(*, pid: str = "p1", text: str = "示例正文", points: int = 10,
              comments: int = 2, days_ago: int = 1, hour: int = 10) -> Post:
    return Post(
        id=pid, account="test:author:demo", platform="hn", url=f"https://x/{pid}",
        published_at=_utc(days_ago, hour), text=text,
        metrics=Metrics(likes=points, comments=comments),
    )


def make_dataset(*, high=None, control=None) -> Dataset:
    high = high or [make_post(pid="h1", text="高表现内容，含数字 3 与结论", points=500, comments=80)]
    control = control or [make_post(pid="n1", text="普通内容，平铺直叙无钩子", points=12, comments=1)]
    return Dataset(
        account="test:author:demo", platform="hn", window_days=30,
        fetched_at=_utc(), provider="local-snapshot",
        source_urls=["https://example.com/snapshot"],
        posts=high + control, high_performers=high, control_group=control,
    )


def make_analysis() -> AnalysisResult:
    return AnalysisResult(
        account="test:author:demo", core_insight="核心洞察占位",
        template=ViralTemplate(name="测试模板"),
    )


@pytest.fixture
def settings(tmp_path):
    """每开一个测试就用独立的资产文件路径，避免污染真实 data/assets。"""
    s = get_settings(reload=True)
    s.asset_file = tmp_path / "content_assets.json"
    return s


@pytest.fixture
def dataset():
    return make_dataset()


@pytest.fixture
def analysis():
    return make_analysis()


@pytest.fixture
def sample_drafts():
    return [
        Draft(id="DRAFT-AA0001", angle="反常识冲突", hook="开头",
              body="正文内容一", cta="评论区聊聊", engine="rule"),
        Draft(id="DRAFT-BB0002", angle="数据清单", hook="开头二",
              body="正文内容二", cta="收藏转发", engine="rule"),
    ]
