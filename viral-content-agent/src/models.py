"""领域数据模型：贯穿"获取 → 分析 → 生成 → 确认 → 入库"全链路的结构体。

统一用 dataclass + to_dict()，保证任何中间态都能序列化进 data/sessions/，
从而支持"分析完暂停 → 人工确认 → 再入库"的跨进程续跑。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


# ======================================================================
# 数据获取层
# ======================================================================
@dataclass
class Metrics:
    """真实公开互动数据。不可得的字段保持 None，绝不填 0 冒充。"""

    likes: Optional[int] = None        # 赞 / points / upvote
    comments: Optional[int] = None     # 评论 / replies
    reposts: Optional[int] = None      # 转发 / share
    collects: Optional[int] = None     # 收藏
    views: Optional[int] = None        # 阅读 / 播放

    @property
    def total(self) -> int:
        """互动总量（转评赞收藏之和，缺失按 0 参与求和但会在报表标注）。"""
        return sum(v for v in (self.likes, self.comments, self.reposts, self.collects) if v)

    @property
    def engagement_rate(self) -> Optional[float]:
        if self.views and self.views > 0:
            return round(self.total / self.views * 100, 3)
        return None

    @property
    def missing_fields(self) -> List[str]:
        names = {"likes": "赞", "comments": "评论", "reposts": "转发", "collects": "收藏", "views": "曝光"}
        return [cn for key, cn in names.items() if getattr(self, key) is None]

    def brief(self) -> str:
        parts = []
        if self.likes is not None:
            parts.append(f"赞{self.likes}")
        if self.comments is not None:
            parts.append(f"评{self.comments}")
        if self.reposts is not None:
            parts.append(f"转{self.reposts}")
        if self.collects is not None:
            parts.append(f"藏{self.collects}")
        if self.views is not None:
            parts.append(f"阅{self.views}")
        return " / ".join(parts) if parts else "数据不可得"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Metrics":
        return cls(**{k: d.get(k) for k in ("likes", "comments", "reposts", "collects", "views")})


@dataclass
class Post:
    """一条真实公开内容。"""

    id: str
    account: str
    platform: str
    url: str
    published_at: str                  # ISO8601
    text: str
    metrics: Metrics = field(default_factory=Metrics)
    media_type: str = "text"           # text | image | video | link
    source: str = ""                   # 抓取通道，用于溯源
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def published_dt(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        except Exception:
            return None

    @property
    def char_len(self) -> int:
        return len(self.text or "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = self.metrics.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Post":
        d = dict(d)
        d["metrics"] = Metrics.from_dict(d.get("metrics") or {})
        d.setdefault("raw", {})
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class Dataset:
    """一次数据获取的完整结果，含溯源信息（供报表标注"真实数据来源"）。"""

    account: str
    platform: str
    window_days: int
    fetched_at: str
    provider: str
    source_urls: List[str] = field(default_factory=list)
    posts: List[Post] = field(default_factory=list)
    high_performers: List[Post] = field(default_factory=list)
    control_group: List[Post] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "platform": self.platform,
            "window_days": self.window_days,
            "fetched_at": self.fetched_at,
            "provider": self.provider,
            "source_urls": self.source_urls,
            "notes": self.notes,
            "posts": [p.to_dict() for p in self.posts],
            "high_performer_ids": [p.id for p in self.high_performers],
            "control_group_ids": [p.id for p in self.control_group],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Dataset":
        posts = [Post.from_dict(p) for p in d.get("posts", [])]
        index = {p.id: p for p in posts}
        ds = cls(
            account=d.get("account", ""),
            platform=d.get("platform", ""),
            window_days=d.get("window_days", 30),
            fetched_at=d.get("fetched_at", ""),
            provider=d.get("provider", ""),
            source_urls=d.get("source_urls", []),
            posts=posts,
            notes=d.get("notes", []),
        )
        ds.high_performers = [index[i] for i in d.get("high_performer_ids", []) if i in index]
        ds.control_group = [index[i] for i in d.get("control_group_ids", []) if i in index]
        return ds


# ======================================================================
# 分析层
# ======================================================================
@dataclass
class DimensionScore:
    key: str
    name: str
    score: int
    insight: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PostAnalysis:
    post_id: str
    group: str                          # high | normal
    dimensions: Dict[str, DimensionScore] = field(default_factory=dict)
    one_line: str = ""

    @property
    def viral_index(self) -> int:
        """六维加权综合分：Hook 与选题权重更高（决定完播/点击）。"""
        weights = {"topic": 0.22, "hook": 0.24, "structure": 0.16,
                   "density": 0.14, "cta": 0.12, "interaction": 0.12}
        if not self.dimensions:
            return 0
        total = sum(self.dimensions[k].score * w for k, w in weights.items() if k in self.dimensions)
        return round(total)

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "group": self.group,
            "one_line": self.one_line,
            "viral_index": self.viral_index,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PostAnalysis":
        dims = {k: DimensionScore(**v) for k, v in (d.get("dimensions") or {}).items()}
        return cls(post_id=d["post_id"], group=d.get("group", "high"),
                   dimensions=dims, one_line=d.get("one_line", ""))


@dataclass
class VariableDiff:
    """单个变量在高表现组 vs 普通组上的差异。"""

    name: str
    kind: str                  # numeric | categorical
    high_value: str
    normal_value: str
    delta: str
    effect: float = 0.0        # 归一化效应量，用于排序
    confidence: str = "疑似相关"
    explanation: str = ""
    actionable: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ViralTemplate:
    name: str
    applicable_scene: str = ""
    blocks: List[Dict[str, str]] = field(default_factory=list)
    hook_patterns: List[str] = field(default_factory=list)
    cta_patterns: List[str] = field(default_factory=list)
    publish_window: str = ""
    checklist: List[str] = field(default_factory=list)
    length_range: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ViralTemplate":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class AnalysisResult:
    account: str
    post_analyses: List[PostAnalysis] = field(default_factory=list)
    variables: List[VariableDiff] = field(default_factory=list)
    core_insight: str = ""
    rejected_hypotheses: List[str] = field(default_factory=list)
    template: Optional[ViralTemplate] = None
    engine: str = "rule"                # rule | llm | llm+rule
    explanatory_power: str = ""          # 文本特征对互动差异的解释力评估（防止过度归因）

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "engine": self.engine,
            "core_insight": self.core_insight,
            "explanatory_power": self.explanatory_power,
            "rejected_hypotheses": self.rejected_hypotheses,
            "post_analyses": [a.to_dict() for a in self.post_analyses],
            "variables": [v.to_dict() for v in self.variables],
            "template": self.template.to_dict() if self.template else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisResult":
        return cls(
            account=d.get("account", ""),
            engine=d.get("engine", "rule"),
            core_insight=d.get("core_insight", ""),
            explanatory_power=d.get("explanatory_power", ""),
            rejected_hypotheses=d.get("rejected_hypotheses", []),
            post_analyses=[PostAnalysis.from_dict(x) for x in d.get("post_analyses", [])],
            variables=[VariableDiff(**v) for v in d.get("variables", [])],
            template=ViralTemplate.from_dict(d["template"]) if d.get("template") else None,
        )


# ======================================================================
# 创作层
# ======================================================================
@dataclass
class Draft:
    id: str
    angle: str
    hook: str
    body: str
    cta: str
    interaction_device: str = ""
    why_it_works: str = ""
    predicted_score: int = 0
    engine: str = "rule"

    def digest_payload(self) -> str:
        return f"{self.id}|{self.hook}|{self.body}|{self.cta}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Draft":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ======================================================================
# 人工确认层
# ======================================================================
@dataclass
class ApprovalToken:
    """人工确认凭证。

    资产库写入方法会校验 token 的 digest 是否与待写入草稿一致，
    以此在代码层面（而非仅流程层面）保证"未经人工确认不可入库"。
    """

    session_id: str
    decision: str                # confirm
    operator: str
    approved_at: str
    digest: str
    selected_ids: List[str] = field(default_factory=list)
    note: str = ""

    @staticmethod
    def make_digest(drafts: List[Draft]) -> str:
        payload = "\n".join(sorted(d.digest_payload() for d in drafts))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def verify(self, drafts: List[Draft]) -> bool:
        return self.decision == "confirm" and self.digest == self.make_digest(drafts)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ApprovalToken":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ======================================================================
# 会话状态机
# ======================================================================
class Stage:
    INIT = "INIT"
    RETRIEVED = "RETRIEVED"
    ANALYZED = "ANALYZED"
    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"   # ← 流程强制暂停点
    APPROVED = "APPROVED"
    LOGGED = "LOGGED"
    ABORTED = "ABORTED"


@dataclass
class Session:
    id: str
    account: str
    stage: str = Stage.INIT
    created_at: str = ""
    updated_at: str = ""
    revision_round: int = 0
    dataset: Optional[Dataset] = None
    analysis: Optional[AnalysisResult] = None
    drafts: List[Draft] = field(default_factory=list)
    approval: Optional[ApprovalToken] = None
    asset_ids: List[str] = field(default_factory=list)
    feedback_history: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account": self.account,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision_round": self.revision_round,
            "dataset": self.dataset.to_dict() if self.dataset else None,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "drafts": [d.to_dict() for d in self.drafts],
            "approval": self.approval.to_dict() if self.approval else None,
            "asset_ids": self.asset_ids,
            "feedback_history": self.feedback_history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        return cls(
            id=d["id"],
            account=d.get("account", ""),
            stage=d.get("stage", Stage.INIT),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            revision_round=d.get("revision_round", 0),
            dataset=Dataset.from_dict(d["dataset"]) if d.get("dataset") else None,
            analysis=AnalysisResult.from_dict(d["analysis"]) if d.get("analysis") else None,
            drafts=[Draft.from_dict(x) for x in d.get("drafts", [])],
            approval=ApprovalToken.from_dict(d["approval"]) if d.get("approval") else None,
            asset_ids=d.get("asset_ids", []),
            feedback_history=d.get("feedback_history", []),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
