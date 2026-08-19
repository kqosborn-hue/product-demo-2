"""第三步（下半）：人工确认（模块化职责四：Human-in-the-loop 交互逻辑）。

这是整条工作流唯一的强制暂停点，也是本项目的合规核心：

1. `render_confirmation_sheet()` 输出《二创内容确认单》——分析结论 + 3 条候选；
2. `wait_for_decision()` 阻塞等待人工输入，只接受 确认 / 修改 / 取消；
3. 只有 decision == confirm 时才签发 `ApprovalToken`，token 内含候选内容的
   sha256 摘要；资产库写入时会校验摘要，因此"改了内容再入库"也会被拦住。

任何绕过本模块直接调用 asset_store.write() 的行为都会抛
HumanApprovalRequired —— 保证闸门在代码层面不可绕过。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from config.prompts import (CONFIRM_ABORT, CONFIRM_ACCEPT, CONFIRM_HINT,
                            CONFIRM_REVISE)
from config.settings import Settings
from .models import AnalysisResult, ApprovalToken, Dataset, Draft
from .utils import console as C
from .utils import text as T

DECISION_CONFIRM = "confirm"
DECISION_REVISE = "revise"
DECISION_ABORT = "abort"


class HumanApprovalRequired(PermissionError):
    """未取得人工确认就试图写库时抛出。"""


class HumanReviewGate:
    def __init__(self, settings: Settings, operator: str = "local-operator"):
        self.settings = settings
        self.operator = operator

    # ================================================================ 确认单
    def render_confirmation_sheet(self, dataset: Dataset, analysis: AnalysisResult,
                                  drafts: List[Draft], session_id: str) -> None:
        C.blank()
        C.rule("《二创内容确认单》", "═", "bright_yellow")
        C.kv("会话 ID", session_id)
        C.kv("目标账号", dataset.account)
        C.kv("数据来源", f"{dataset.provider}（真实公开数据，抓取于 {dataset.fetched_at[:19]}）")
        C.kv("样本构成", f"窗口 {dataset.window_days} 天 / 总样本 {len(dataset.posts)} 条 / "
                         f"高表现 {len(dataset.high_performers)} 条 / 对照组 {len(dataset.control_group)} 条")
        C.kv("分析引擎", analysis.engine)

        # ---- 一、核心洞察
        C.blank()
        print("  " + C.c("一、核心洞察", "bold", "bright_cyan"))
        C.wrapped(analysis.core_insight, indent=4)
        if analysis.explanatory_power:
            C.blank()
            C.wrapped(C.c("【解释力自评】" + analysis.explanatory_power,
                          "yellow" if analysis.explanatory_power.startswith("解释力弱") else "gray"),
                      indent=4)

        # ---- 二、关键变量（差异归因）
        strong = [v for v in analysis.variables if v.confidence != "噪声"][:6]
        C.table(
            ["关键变量", "高表现组", "普通内容组", "差值", "置信度", "下次怎么用"],
            [[v.name, v.high_value, v.normal_value, v.delta, v.confidence, v.actionable]
             for v in strong],
            aligns=["left", "right", "right", "right", "center", "left"],
            title="二、导致数据差异的关键变量",
            highlight_rows=[i for i, v in enumerate(strong) if v.confidence == "强因果"],
        )

        # ---- 三、爆款模板
        tpl = analysis.template
        if tpl:
            C.blank()
            print("  " + C.c(f"三、沉淀出的可复用模板：《{tpl.name}》", "bold", "bright_cyan"))
            C.kv("适用场景", tpl.applicable_scene, 12)
            C.kv("篇幅区间", tpl.length_range, 12)
            C.kv("建议时段", tpl.publish_window, 12)
            for i, b in enumerate(tpl.blocks, 1):
                C.bullet(f"{C.c(str(i) + '. ' + b.get('role',''), 'bold')} → {b.get('goal','')} "
                         f"{C.c('[' + b.get('rule','') + ']', 'gray')}", indent=4)

        # ---- 四、候选内容
        C.blank()
        print("  " + C.c(f"四、候选二创内容（共 {len(drafts)} 条，等待人工审核）", "bold", "bright_cyan"))
        best = max((d.predicted_score for d in drafts), default=100) or 100
        for idx, d in enumerate(drafts, 1):
            C.blank()
            head = (f"  {C.c(f' 候选 {idx} ', 'on_blue', 'white', 'bold')} "
                    f"{C.c(d.angle, 'bold', 'bright_yellow')}  "
                    f"{C.c(f'[{d.id}]', 'gray')}  "
                    f"预测指数 {C.c(str(d.predicted_score), 'bright_green', 'bold')} "
                    f"{C.bar(d.predicted_score, max(best, 1), 14)}  "
                    f"{C.c('引擎:' + d.engine, 'gray')}")
            print(head)
            C.quote(d.body, indent=4)
            C.kv("    CTA", d.cta, 14)
            C.kv("    互动装置", d.interaction_device or "-", 14)
            C.kv("    命中规则", T.truncate(d.why_it_works, 84), 14)

        # ---- 五、数据溯源与免责
        C.blank()
        print("  " + C.c("五、数据溯源", "bold", "bright_cyan"))
        for u in (dataset.source_urls or ["（无）"])[:3]:
            C.bullet(T.truncate(u, 96), indent=4, marker="↗")
        for n in dataset.notes[:4]:
            C.bullet(C.c(n, "yellow"), indent=4, marker="!")
        C.rule("", "═", "bright_yellow")

    # ================================================================ 阻塞等待
    def wait_for_decision(self, drafts: List[Draft], session_id: str,
                          reader: Optional[Callable[[str], str]] = None
                          ) -> Tuple[str, Optional[ApprovalToken], str]:
        """强制暂停，等待人工输入。返回 (decision, token, feedback)。"""
        C.human_gate(CONFIRM_HINT, hint="确认 / 修改 / 取消（可在 '确认' 后附编号，如：确认 1,3）")
        ask = reader or C.ask
        while True:
            raw = (ask("请输入指令") or "").strip()
            if not raw:
                C.warn("未检测到输入。人工确认是硬性环节，请输入 确认 / 修改 / 取消。")
                continue
            head = raw.split()[0].lower()
            rest = raw[len(head):].strip()

            if head in CONFIRM_ACCEPT:
                selected = self._parse_selection(rest, drafts)
                token = ApprovalToken(
                    session_id=session_id, decision=DECISION_CONFIRM, operator=self.operator,
                    approved_at=datetime.now(timezone.utc).isoformat(),
                    digest=ApprovalToken.make_digest(drafts),
                    selected_ids=[d.id for d in selected],
                    note=f"人工确认，选中 {len(selected)}/{len(drafts)} 条",
                )
                C.ok(f"已收到人工确认（操作人 {self.operator}），选中 {len(selected)} 条，"
                     f"凭证摘要 {token.digest[:12]}…")
                return DECISION_CONFIRM, token, ""
            if head in CONFIRM_REVISE:
                feedback = rest or (ask("请补充修改意见（可直接回车跳过）") or "").strip()
                C.warn(f"进入修改轮次。意见：{feedback or '（未填写，将自动换角度重写）'}")
                return DECISION_REVISE, None, feedback
            if head in CONFIRM_ABORT:
                C.err("人工取消，工作流终止，未写入任何内容。")
                return DECISION_ABORT, None, ""
            C.warn(f"无法识别指令「{raw}」。请输入 确认 / 修改 / 取消。")

    # ================================================================ 工具
    @staticmethod
    def _parse_selection(rest: str, drafts: List[Draft]) -> List[Draft]:
        """支持「确认 1,3」只入库指定候选；不填则全选。"""
        import re

        nums = [int(x) for x in re.findall(r"\d+", rest or "")]
        picked = [drafts[i - 1] for i in nums if 1 <= i <= len(drafts)]
        return picked or list(drafts)

    @staticmethod
    def assert_approved(token: Optional[ApprovalToken], drafts: List[Draft],
                        session_id: str) -> None:
        """入库前的最终闸门校验（asset_store 调用）。"""
        if token is None:
            raise HumanApprovalRequired(
                "拒绝写入资产库：缺少人工确认凭证（ApprovalToken）。"
                "请先通过 HumanReviewGate.wait_for_decision() 取得确认。")
        if token.decision != DECISION_CONFIRM:
            raise HumanApprovalRequired(f"拒绝写入资产库：人工决策为 {token.decision}，非 confirm。")
        if token.session_id != session_id:
            raise HumanApprovalRequired("拒绝写入资产库：确认凭证与当前会话不匹配。")
        if not token.verify(drafts):
            raise HumanApprovalRequired(
                "拒绝写入资产库：待写入内容与人工确认时的内容不一致（摘要校验失败）。"
                "内容一旦在确认后被修改，必须重新走人工确认。")
