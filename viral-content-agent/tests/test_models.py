"""领域模型测试：序列化往返、缺失字段语义、人工确认凭证摘要校验。"""

import pytest

from src.models import (ApprovalToken, Draft, Metrics, Post, Session, Stage)


def test_metrics_missing_fields_marked_none():
    m = Metrics(likes=10)   # 评论/转发/收藏/曝光均不可得
    assert m.likes == 10
    assert m.comments is None
    assert "评论" in m.missing_fields
    # 缺失字段不参与"冒充"，仅以可得字段求和
    assert m.total == 10


def test_metrics_round_trip():
    m = Metrics(likes=5, comments=3, reposts=1, collects=2, views=100)
    assert Metrics.from_dict(m.to_dict()) == m


def test_post_round_trip():
    p = Post(id="x1", account="a", platform="hn", url="u",
             published_at="2026-08-01T10:00:00+00:00", text="t",
             metrics=Metrics(likes=9, comments=2))
    assert Post.from_dict(p.to_dict()) == p


def test_approval_digest_consistent_and_tamper_proof():
    drafts = [Draft(id="D1", angle="a", hook="h", body="b", cta="c")]
    tok = ApprovalToken(session_id="S1", decision="confirm", operator="op",
                        approved_at="t", digest=ApprovalToken.make_digest(drafts))
    assert tok.verify(drafts) is True
    # 正文被篡改 → 摘要校验必须失败（防止"确认后改内容再入库"绕过闸门）
    tampered = [Draft(id="D1", angle="a", hook="h", body="CHANGED", cta="c")]
    assert tok.verify(tampered) is False


def test_approval_digest_changes_with_content():
    d1 = [Draft(id="D1", angle="a", hook="h", body="b", cta="c")]
    d2 = [Draft(id="D2", angle="x", hook="y", body="z", cta="w")]
    assert ApprovalToken.make_digest(d1) != ApprovalToken.make_digest(d2)


def test_session_round_trip(tmp_path):
    s = Session(id="S1", account="a", stage=Stage.LOGGED, asset_ids=["ASSET-1"])
    restored = Session.from_dict(s.to_dict())
    assert restored.stage == Stage.LOGGED
    assert restored.asset_ids == ["ASSET-1"]
