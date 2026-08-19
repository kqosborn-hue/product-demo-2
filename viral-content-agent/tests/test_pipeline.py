"""端到端管线测试：用本地真实抓取快照，完整跑完"获取→分析→生成→确认→入库"。

不依赖外网、不依赖 LLM Key（自动降级规则引擎），
直接验证"人工确认"是入库的唯一通路。
"""

from config.settings import get_settings

from src.agent import ContentAgent, Stage


def test_pipeline_snapshot_non_interactive_then_confirm(settings):
    agent = ContentAgent(settings=settings, operator="tester", verbose=False)
    session = agent.run(account="hn:author:pseudolus", source="snapshot",
                         interactive=False)
    # 第三步后必须强制停在人工确认，不得自动入库
    assert session.stage == Stage.AWAITING_APPROVAL
    assert len(session.drafts) >= 3

    # 模拟人工确认（只入库第 1、2 条），应当走通并落库
    session2 = agent.resume(session.id, "确认 1,2")
    assert session2.stage == Stage.LOGGED
    assert len(session2.asset_ids) == 2
    for aid in session2.asset_ids:
        assert aid.startswith("ASSET-")


def test_pipeline_abort_does_not_write(settings):
    agent = ContentAgent(settings=settings, operator="tester", verbose=False)
    session = agent.run(account="hn:author:pseudolus", source="snapshot",
                         interactive=False)
    session2 = agent.resume(session.id, "取消")
    assert session2.stage == Stage.ABORTED
    assert session2.asset_ids == []
