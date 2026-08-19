"""资产库测试：入库硬闸门 + 真实写入。"""

import pytest

from src.asset_store import JsonAssetStore
from src.human_review import HumanApprovalRequired
from src.models import (AnalysisResult, ApprovalToken, Dataset, Draft,
                        ViralTemplate)
from tests.conftest import make_dataset


def _token(drafts, session_id="S1"):
    return ApprovalToken(session_id=session_id, decision="confirm", operator="tester",
                         approved_at="2026-08-01T00:00:00+00:00",
                         digest=ApprovalToken.make_digest(drafts),
                         selected_ids=[d.id for d in drafts])


def test_commit_blocked_without_approval(settings):
    store = JsonAssetStore(settings)
    ds = make_dataset()
    analysis = AnalysisResult(account="test:author:demo", template=ViralTemplate(name="t"))
    drafts = [Draft(id="D1", angle="a", hook="h", body="b", cta="c")]
    with pytest.raises(HumanApprovalRequired):
        store.commit("S1", ds, analysis, drafts, None)


def test_commit_writes_with_valid_approval(settings):
    store = JsonAssetStore(settings)
    ds = make_dataset()
    analysis = AnalysisResult(account="test:author:demo", template=ViralTemplate(name="t"))
    drafts = [Draft(id="D1", angle="a", hook="h", body="b", cta="c", predicted_score=80)]
    token = _token(drafts)
    records = store.commit("S1", ds, analysis, drafts, token)
    assert len(records) == 1
    assert records[0]["asset_id"].startswith("ASSET-")
    assert records[0]["approved_by"] == "tester"
    # 二次读取验证已落盘
    assert len(store.list_assets()) == 1


def test_commit_respects_partial_selection(settings):
    store = JsonAssetStore(settings)
    ds = make_dataset()
    analysis = AnalysisResult(account="test:author:demo", template=ViralTemplate(name="t"))
    drafts = [Draft(id=f"D{i}", angle="a", hook="h", body="b", cta="c") for i in (1, 2, 3)]
    token = _token(drafts)
    token.selected_ids = ["D1", "D3"]   # 只入库 1、3
    records = store.commit("S1", ds, analysis, drafts, token)
    assert {r["draft_id"] for r in records} == {"D1", "D3"}
