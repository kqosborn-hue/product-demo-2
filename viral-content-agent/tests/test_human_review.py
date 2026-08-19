"""人工确认闸门测试：代码层面保证"未经确认不可入库"。"""

import pytest

from src.human_review import (DECISION_CONFIRM, HumanApprovalRequired,
                              HumanReviewGate)
from src.models import ApprovalToken, Dataset, Draft
from tests.conftest import make_dataset


def test_assert_raises_without_token():
    with pytest.raises(HumanApprovalRequired):
        HumanReviewGate.assert_approved(None, [], "S1")


def test_assert_rejects_wrong_session():
    tok = ApprovalToken(session_id="S1", decision=DECISION_CONFIRM, operator="o",
                        approved_at="t", digest="x")
    with pytest.raises(HumanApprovalRequired):
        HumanReviewGate.assert_approved(tok, [], "S2")


def test_assert_rejects_non_confirm():
    tok = ApprovalToken(session_id="S1", decision="revise", operator="o",
                        approved_at="t", digest="x")
    with pytest.raises(HumanApprovalRequired):
        HumanReviewGate.assert_approved(tok, [], "S1")


def test_assert_rejects_tampered_content(sample_drafts):
    tok = ApprovalToken(session_id="S1", decision=DECISION_CONFIRM, operator="o",
                        approved_at="t",
                        digest=ApprovalToken.make_digest(sample_drafts))
    tampered = [Draft(id=d.id, angle=d.angle, hook=d.hook,
                      body=d.body + " 篡改", cta=d.cta) for d in sample_drafts]
    with pytest.raises(HumanApprovalRequired):
        HumanReviewGate.assert_approved(tok, tampered, "S1")


def test_parse_selection_supports_partial():
    drafts = [Draft(id=f"D{i}", angle="a", hook="h", body="b", cta="c")
              for i in range(1, 4)]
    picked = HumanReviewGate._parse_selection("确认 1,3", drafts)
    assert [d.id for d in picked] == ["D1", "D3"]
    # 不指定编号 → 全选
    assert len(HumanReviewGate._parse_selection("", drafts)) == 3
