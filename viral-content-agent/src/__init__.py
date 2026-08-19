"""爆款内容拆解与二创 Agent —— 核心包。

模块化职责划分（对应 README「架构」一节）：
    data_retrieval.py  真实公开数据获取与高低分组
    analyzer.py        数据分析逻辑（六维拆解 / 差异归因 / 公式沉淀）
    creator.py         内容生成逻辑（二次创作）
    human_review.py    人工确认交互逻辑（HITL 硬闸门）
    asset_store.py     资产入库（json / notion / feishu）
    agent.py           工作流编排（状态机 + 会话持久化）
"""

__version__ = "1.0.0"

from .agent import ContentAgent  # noqa: E402,F401
from .models import Stage  # noqa: E402,F401

__all__ = ["ContentAgent", "Stage", "__version__"]
