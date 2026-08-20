#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""爆款内容拆解与二创 Agent —— CLI 入口。

    # 完整跑一遍（真实抓取 → 分析 → 生成 → 人工确认 → 入库）
    python main.py run --account "hn:author:pseudolus"

    # 只跑到人工确认就停下（适合把确认单交给他人审核）
    python main.py run --account "reddit:r/LocalLLaMA" --non-interactive

    # 审核完成后续跑入库（'确认 1,3' 表示只入库第 1、3 条）
    python main.py resume --session S20260820... --decision "确认 1,3"

    # 查看资产库 / 会话
    python main.py assets
    python main.py sessions
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import SESSION_DIR, get_settings  # noqa: E402
from src.agent import ContentAgent  # noqa: E402
from src.asset_store import get_asset_store  # noqa: E402
from src.utils import console as C  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="viral-content-agent",
        description="爆款内容拆解与二创 Agent：真实公开数据对比分析 + 人工确认后入库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command")

    run = sub.add_parser("run", help="运行完整工作流")
    run.add_argument("--account", "-a", help="目标账号链接/名称，如 hn:author:pseudolus、@handle、https://...")
    run.add_argument("--days", "-d", type=int, help="回溯天数（默认 30）")
    run.add_argument("--limit", "-l", type=int, help="最多抓取条数（默认 60）")
    run.add_argument("--source", "-s", choices=["auto", "live", "snapshot"],
                     help="数据通道：auto=实时优先失败回落快照；live=只用实时；snapshot=只用本地真实快照")
    run.add_argument("--operator", default="local-operator", help="确认人标识（写入资产库审计字段）")
    run.add_argument("--non-interactive", action="store_true",
                     help="停在人工确认环节并退出（后续用 resume 确认）")
    run.add_argument("--no-snapshot", action="store_true", help="不保存本次抓取快照")
    run.add_argument("--no-color", action="store_true", help="禁用颜色输出")

    res = sub.add_parser("resume", help="人工确认后续跑（入库 / 修改）")
    res.add_argument("--session", "-S", required=True, help="会话 ID")
    res.add_argument("--decision", "-D", required=True, help="确认 / 修改 / 取消（可写 '确认 1,3'）")
    res.add_argument("--feedback", "-f", default="", help="选择'修改'时的审核意见")
    res.add_argument("--operator", default="local-operator")
    res.add_argument("--no-color", action="store_true")

    sub.add_parser("assets", help="查看内容资产库")
    sub.add_parser("sessions", help="查看历史会话")

    show = sub.add_parser("show", help="查看某个会话详情")
    show.add_argument("--session", "-S", required=True)
    return p


def cmd_run(args) -> int:
    agent = ContentAgent(operator=args.operator)
    session = agent.run(account=args.account, days=args.days, limit=args.limit,
                        source=args.source, save_snapshot=not args.no_snapshot,
                        interactive=not args.non_interactive)
    C.blank()
    C.kv("最终状态", C.c(session.stage, "bold"))
    C.kv("会话文件", str(ContentAgent.session_path(session.id)))
    if session.asset_ids:
        C.kv("入库资产", ", ".join(session.asset_ids))
    return 0


def cmd_resume(args) -> int:
    agent = ContentAgent(operator=args.operator)
    session = agent.resume(args.session, args.decision, feedback=args.feedback)
    C.blank()
    C.kv("最终状态", C.c(session.stage, "bold"))
    if session.asset_ids:
        C.kv("入库资产", ", ".join(session.asset_ids))
    return 0


def cmd_assets(_args) -> int:
    store = get_asset_store(get_settings())
    assets = store.list_assets()
    if not assets:
        C.warn("资产库为空。跑一次 run 并在确认环节输入 '确认' 即可入库。")
        return 0
    C.table(["资产ID", "创建时间", "角度", "开头", "预测指数", "确认人", "状态"],
            [[a["asset_id"], a["created_at"][:16], a["angle"],
              a["hook"], a["predicted_score"], a["approved_by"], a["status"]]
             for a in assets],
            aligns=["left", "center", "left", "left", "right", "left", "center"],
            title=f"内容资产库（共 {len(assets)} 条）")
    return 0


def cmd_sessions(_args) -> int:
    files = sorted(Path(SESSION_DIR).glob("*.json"), reverse=True)
    if not files:
        C.warn("暂无历史会话。")
        return 0
    rows = []
    for f in files[:25]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append([d.get("id"), d.get("account"), d.get("stage"),
                     (d.get("updated_at") or "")[:16], len(d.get("drafts") or []),
                     ", ".join(d.get("asset_ids") or []) or "-"])
    C.table(["会话ID", "账号", "状态", "更新时间", "候选数", "入库资产"], rows,
            title=f"历史会话（{len(files)} 个）")
    return 0


def cmd_show(args) -> int:
    p = ContentAgent.session_path(args.session)
    if not p.exists():
        C.err(f"找不到会话：{p}")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "no_color", False):
        C.set_color(False)
    if not args.command:
        parser.print_help()
        return 0
    try:
        return {"run": cmd_run, "resume": cmd_resume, "assets": cmd_assets,
                "sessions": cmd_sessions, "show": cmd_show}[args.command](args)
    except KeyboardInterrupt:
        C.blank()
        C.err("已被用户中断（未入库任何内容）。")
        return 130
    except Exception as exc:
        C.err(f"运行失败：{exc}")
        if "--debug" in sys.argv:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
