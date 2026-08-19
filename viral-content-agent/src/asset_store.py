"""第四步：资产入库与记录。

三种后端（由 ASSET_BACKEND 切换）：
- json   本地 data/assets/content_assets.json（默认，零配置可演示）
- notion Notion Database（需 NOTION_TOKEN / NOTION_DATABASE_ID）
- feishu 飞书多维表格（需 FEISHU_* 四项配置）

所有后端写入前都会走 HumanReviewGate.assert_approved()：
没有有效人工确认凭证 → 抛 HumanApprovalRequired，一条也写不进去。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config.settings import Settings
from .human_review import HumanReviewGate
from .models import AnalysisResult, ApprovalToken, Dataset, Draft
from .utils.http import post_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_asset_id() -> str:
    return f"ASSET-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"


class BaseAssetStore:
    backend = "base"

    def __init__(self, settings: Settings, logger: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.log = logger or (lambda msg: None)

    # ---------------------------------------------------------------- 公共入口
    def commit(self, session_id: str, dataset: Dataset, analysis: AnalysisResult,
               drafts: List[Draft], token: Optional[ApprovalToken]) -> List[Dict]:
        """写入资产库。必须携带有效人工确认凭证。"""
        HumanReviewGate.assert_approved(token, drafts, session_id)   # ← 硬闸门
        selected = [d for d in drafts if not token.selected_ids or d.id in token.selected_ids]
        records = [self._build_record(session_id, dataset, analysis, d, token) for d in selected]
        self._persist(records)
        return records

    # ---------------------------------------------------------------- 记录结构
    def _build_record(self, session_id: str, dataset: Dataset, analysis: AnalysisResult,
                      draft: Draft, token: ApprovalToken) -> Dict:
        return {
            "asset_id": make_asset_id(),
            "session_id": session_id,
            "created_at": _now(),
            "status": "待追踪",
            "source_account": dataset.account,
            "source_platform": dataset.platform,
            "data_provider": dataset.provider,
            "data_fetched_at": dataset.fetched_at,
            "template_name": analysis.template.name if analysis.template else "",
            "core_insight": analysis.core_insight,
            "angle": draft.angle,
            "hook": draft.hook,
            "content": draft.body,
            "cta": draft.cta,
            "interaction_device": draft.interaction_device,
            "predicted_score": draft.predicted_score,
            "generation_engine": draft.engine,
            "draft_id": draft.id,
            "approved_by": token.operator,
            "approved_at": token.approved_at,
            "approval_digest": token.digest,
            "tracking": {"published_at": None, "likes": None, "comments": None,
                         "reposts": None, "review_note": ""},
        }

    def _persist(self, records: List[Dict]) -> None:
        raise NotImplementedError

    # ---------------------------------------------------------------- 查询
    def list_assets(self) -> List[Dict]:
        return []


class JsonAssetStore(BaseAssetStore):
    backend = "json"

    @property
    def path(self) -> Path:
        return Path(self.settings.asset_file)

    def _load(self) -> Dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.log(f"资产库文件损坏，已备份并重建：{self.path}")
                self.path.rename(self.path.with_suffix(".bak.json"))
        return {"schema_version": 1, "assets": []}

    def _persist(self, records: List[Dict]) -> None:
        db = self._load()
        db.setdefault("assets", []).extend(records)
        db["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"已写入本地资产库：{self.path}")

    def list_assets(self) -> List[Dict]:
        return self._load().get("assets", [])


class NotionAssetStore(BaseAssetStore):
    backend = "notion"

    def _persist(self, records: List[Dict]) -> None:
        s = self.settings
        if not (s.notion_token and s.notion_database_id):
            raise RuntimeError("缺少 NOTION_TOKEN / NOTION_DATABASE_ID（见 .env.example）")
        headers = {"Authorization": f"Bearer {s.notion_token}",
                   "Notion-Version": "2022-06-28"}
        for r in records:
            payload = {
                "parent": {"database_id": s.notion_database_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": r["hook"][:180]}}]},
                    "AssetID": {"rich_text": [{"text": {"content": r["asset_id"]}}]},
                    "Angle": {"rich_text": [{"text": {"content": r["angle"]}}]},
                    "Status": {"select": {"name": r["status"]}},
                    "PredictedScore": {"number": r["predicted_score"]},
                    "ApprovedBy": {"rich_text": [{"text": {"content": r["approved_by"]}}]},
                },
                "children": [{
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text",
                                                 "text": {"content": r["content"][:1900]}}]},
                }],
            }
            post_json("https://api.notion.com/v1/pages", payload, headers=headers, timeout=40)
            self.log(f"已写入 Notion：{r['asset_id']}")


class FeishuAssetStore(BaseAssetStore):
    backend = "feishu"

    def _token(self) -> str:
        s = self.settings
        data = post_json("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                         {"app_id": s.feishu_app_id, "app_secret": s.feishu_app_secret}, timeout=30)
        if not data.get("tenant_access_token"):
            raise RuntimeError(f"飞书鉴权失败：{data}")
        return data["tenant_access_token"]

    def _persist(self, records: List[Dict]) -> None:
        s = self.settings
        if not (s.feishu_app_id and s.feishu_app_secret and s.feishu_bitable_app_token
                and s.feishu_bitable_table_id):
            raise RuntimeError("缺少 FEISHU_* 配置（见 .env.example）")
        token = self._token()
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/{s.feishu_bitable_app_token}"
               f"/tables/{s.feishu_bitable_table_id}/records/batch_create")
        fields = [{"fields": {
            "资产ID": r["asset_id"], "角度": r["angle"], "开头": r["hook"],
            "正文": r["content"], "CTA": r["cta"], "预测指数": r["predicted_score"],
            "来源账号": r["source_account"], "模板": r["template_name"],
            "确认人": r["approved_by"], "状态": r["status"],
        }} for r in records]
        post_json(url, {"records": fields},
                  headers={"Authorization": f"Bearer {token}"}, timeout=40)
        self.log(f"已写入飞书多维表格 {len(records)} 条记录")


def get_asset_store(settings: Settings, logger: Optional[Callable[[str], None]] = None
                    ) -> BaseAssetStore:
    return {"json": JsonAssetStore, "notion": NotionAssetStore,
            "feishu": FeishuAssetStore}.get(settings.asset_backend, JsonAssetStore)(settings, logger)
