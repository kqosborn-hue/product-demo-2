"""分析引擎测试：六维打分、方向感知归因、解释力自评、模板沉淀。

重点验证：归因建议必须与数据方向一致（不能给反向指令）。
"""

from config.settings import get_settings

from src.analyzer import ContentAnalyzer, ScoreEngine
from tests.conftest import make_analysis, make_dataset, make_post


def test_score_engine_returns_six_dimensions():
    p = make_post(text="别再踩坑了！3 个方法让你翻倍。评论区聊聊你的看法")
    pa, _ = ScoreEngine.analyze_post(p, "high")
    assert set(pa.dimensions) == {"topic", "hook", "structure", "density", "cta", "interaction"}
    for d in pa.dimensions.values():
        assert 0 <= d.score <= 100
    assert 0 <= pa.viral_index <= 100


def test_analyze_full_pipeline():
    ds = make_dataset()
    res = ContentAnalyzer(get_settings()).analyze(ds)
    assert len(res.post_analyses) == 2
    assert res.core_insight
    assert res.template is not None
    assert res.engine  # rule / llm / llm+rule


def test_actionable_number_direction_aware():
    # 高表现组更常含数字 → 建议"放入数字"
    assert "放入具体数字" in ContentAnalyzer._actionable("has_number", 1.0, 0.3)
    # 高表现组反而更不常含数字 → 不能建议加数字
    assert "牺牲可读性" in ContentAnalyzer._actionable("has_number", 0.2, 0.9)
    # 两组一致 → 不是差异来源
    assert "不是差异来源" in ContentAnalyzer._actionable("has_number", 0.5, 0.5)


def test_actionable_numeric_direction_aware():
    # 高表现组首句更短 → 建议"压缩到"
    assert "压缩到" in ContentAnalyzer._actionable("hook_len", 200.0, 500.0)
    # 高表现组首句更长 → 建议"提高到"
    assert "提高到" in ContentAnalyzer._actionable("hook_len", 800.0, 400.0)


def test_actionable_categorical_uses_high_value():
    out = ContentAnalyzer._actionable("hook_type", "冲突反常识型", "平铺直叙型")
    assert "冲突反常识型" in out


def test_explanatory_power_rejects_over_attribution():
    """当六维几乎无差异但真实互动差很大时，必须提示解释力弱。"""
    # 构造两组写法相近、但互动量差 100x 的样本
    high = [make_post(pid=f"h{i}", text="普通陈述句，无钩子无数字。", points=1000, comments=900)
            for i in range(3)]
    norm = [make_post(pid=f"n{i}", text="普通陈述句，无钩子无数字。", points=10, comments=9)
            for i in range(3)]
    ds = make_dataset(high=high, control=norm)
    res = ContentAnalyzer(get_settings()).analyze(ds)
    assert "解释力弱" in res.explanatory_power
