"""二次创作测试：无 LLM 时规则引擎仍产出 ≥3 条结构完整的候选。"""

from config.settings import get_settings

from src.creator import ContentCreator
from src.models import AnalysisResult, ViralTemplate


def test_create_returns_at_least_three():
    creator = ContentCreator(get_settings())
    analysis = AnalysisResult(account="test:author:demo",
                              core_insight="开头交付冲突决定上限",
                              template=ViralTemplate(name="冲突反常识型·低门槛互动型（补齐项）结构模板"))
    drafts = creator.create(analysis, n=3)
    assert len(drafts) >= 3


def test_drafts_have_cta_and_score():
    creator = ContentCreator(get_settings())
    analysis = AnalysisResult(account="test:author:demo", core_insight="x",
                              template=ViralTemplate(name="t"))
    drafts = creator.create(analysis, n=3)
    for d in drafts:
        assert d.cta, "每条候选必须带有 CTA（人工确认单要求完整结构）"
        assert d.predicted_score >= 0, "生成即自检：应带六维反向打分"
        assert d.body.strip()


def test_three_distinct_angles():
    creator = ContentCreator(get_settings())
    analysis = AnalysisResult(account="test:author:demo", core_insight="x",
                              template=ViralTemplate(name="t"))
    drafts = creator.create(analysis, n=3)
    angles = {d.angle for d in drafts}
    assert len(angles) >= 2, "三条候选应覆盖不同角度"
