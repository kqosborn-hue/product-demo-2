#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键演示脚本（录屏/答辩用）。

    python demo.py                     # 默认账号，实时抓真实公开数据，失败自动回落快照
    python demo.py hn:author:pseudolus  # 指定账号
    python demo.py --offline            # 强制离线，用本地真实抓取快照

演示要点：
1. 全程打印思考过程与对比表格；
2. 走到第三步会强制暂停，屏幕上出现黄框「HUMAN-IN-THE-LOOP」等待输入；
3. 输入 '确认' 才会写入资产库并打印入库日志；输入 '修改' 会重新生成候选。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent import ContentAgent  # noqa: E402
from src.utils import console as C  # noqa: E402

DEFAULT_ACCOUNT = "hn:author:pseudolus"   # Hacker News 公开账号，免密钥即可复现


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    offline = "--offline" in sys.argv
    account = args[0] if args else DEFAULT_ACCOUNT

    C.blank()
    C.rule("DEMO 开始", "═", "cyan")
    C.info(f"目标账号：{account}")
    C.info(f"数据通道：{'本地真实抓取快照（离线模式）' if offline else '实时真实公开数据（失败自动回落快照）'}")
    C.info("提示：走到第三步会出现黄色暂停框，输入 '确认' 入库，或输入 '修改' 重生成。")

    agent = ContentAgent(operator="demo-reviewer")
    session = agent.run(account=account, source="snapshot" if offline else "auto")

    C.blank()
    C.kv("最终状态", C.c(session.stage, "bold"))
    if session.asset_ids:
        C.kv("入库资产", ", ".join(session.asset_ids))
        C.info("可执行 `python main.py assets` 查看资产库全部记录。")
    else:
        C.warn("本次未入库（人工未确认或已取消）——这正是人工确认闸门在起作用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
