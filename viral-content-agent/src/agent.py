"""工作流编排器：把四个步骤串成一个可暂停、可续跑的状态机。

状态流转：
    INIT → RETRIEVED → ANALYZED → DRAFTED → AWAITING_APPROVAL
                                                 ├─ 确认 → APPROVED → LOGGED
                                                 ├─ 修改 → DRAFTED（回到生成，最多 N 轮）
                                                 └─ 取消 → ABORTED

会话全程落盘 data/sessions/<id>.json，因此支持：
    python main.py run --account ... --non-interactive   # 停在 AWAITING_APPROVAL
    python main.py resume --session <id> --decision 确认  # 人工确认后再入库
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from config.prompts import SYSTEM_PROMPT
from config.settings import SESSION_DIR, Settings, get_settings
from .analyzer import ContentAnalyzer
from .asset_store import get_asset_store
from .creator import ContentCreator
from .data_retrieval import DataRetriever
from .human_review import (DECISION_ABORT, DECISION_CONFIRM, DECISION_REVISE,
                           HumanReviewGate)
from .llm_client import LLMClient
from .models import (AnalysisResult, ApprovalToken, Dataset, Draft, Session, Stage)
from .utils import console as C
from .utils import text as T

TOTAL_STEPS = 4


class ContentAgent:
    def __init__(self, settings: Optional[Settings] = None, operator: str = "local-operator",
                 verbose: bool = True):
        self.settings = settings or get_settings()
        self.verbose = verbose
        self.llm = LLMClient(self.settings)
        self.retriever = DataRetriever(self.settings, logger=self._log)
        self.analyzer = ContentAnalyzer(self.settings, self.llm, logger=self._log)
        self.creator = ContentCreator(self.settings, self.llm, logger=self._log)
        self.gate = HumanReviewGate(self.settings, operator=operator)
        self.store = get_asset_store(self.settings, logger=self._log)
        self._thoughts: List[str] = []

    # ================================================================ 日志
    def _log(self, msg: str) -> None:
        self._thoughts.append(msg)

    def _flush_thoughts(self, header: str = "思考过程") -> None:
        if self.verbose and self._thoughts:
            C.think(self._thoughts, header)
        self._thoughts = []

    # ================================================================ 主流程
    def run(self, account: Optional[str] = None, days: Optional[int] = None,
            limit: Optional[int] = None, source: Optional[str] = None,
            save_snapshot: bool = True, interactive: bool = True,
            reader: Optional[Callable[[str], str]] = None) -> Session:
        account = account or self.settings.default_account
        session = Session(
            id="S" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4],
            account=account, stage=Stage.INIT,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        if self.verbose:
            C.banner("爆款内容拆解与二创 Agent",
                     f"会话 {session.id} · 分析引擎 {self.llm.label} · 资产后端 {self.store.backend}")
            C.blank()
            print("  " + C.c("【角色设定】", "bold", "magenta") +
                  C.c(" 精通社交媒体算法的内容策略专家 · 数据驱动 / 逻辑严密 / 极具创意", "gray"))
            C.kv("目标账号", C.c(account, "bold", "bright_white"))
            C.kv("时间窗口", f"最近 {days or self.settings.lookback_days} 天")
            C.kv("人工确认", C.c("强制开启（不可通过配置关闭）", "bright_yellow", "bold"))

        # ---------------- 第一步 ----------------
        self._step1(session, account, days, limit, source, save_snapshot)
        # ---------------- 第二步 ----------------
        self._step2(session)
        # ---------------- 第三步 ----------------
        self._step3(session, interactive=interactive, reader=reader)
        # ---------------- 第四步 ----------------
        if session.stage == Stage.APPROVED:
            self._step4(session)
        return session

    # ---------------------------------------------------------------- Step 1
    def _step1(self, session: Session, account: str, days, limit, source, save_snapshot) -> None:
        if self.verbose:
            C.step(1, TOTAL_STEPS, "真实数据获取与筛选（Data Retrieval）")
            C.action("解析账号定位符 → 选择真实公开数据通道 → 拉取近 30 天内容 → 划分高表现/对照组")
        dataset = self.retriever.retrieve(account, days=days, limit=limit, source=source)
        session.dataset = dataset
        session.stage = Stage.RETRIEVED
        self._flush_thoughts("数据获取思考过程")
        if save_snapshot and dataset.provider != "local-snapshot":
            path = self.retriever.save_snapshot(dataset)
            if self.verbose:
                C.ok(f"真实抓取结果已存快照（保证结论可复算）：{path.name}")
        if self.verbose:
            C.ok(f"通道 {dataset.provider} 返回 {len(dataset.posts)} 条真实公开内容")
            for n in dataset.notes:
                C.warn(n)
            self._print_sample_table(dataset)
        self._save(session)

    def _print_sample_table(self, dataset: Dataset) -> None:
        rows, highlight = [], []
        ordered = dataset.high_performers + dataset.control_group
        for i, p in enumerate(ordered):
            group = "🔥高表现" if p in dataset.high_performers else "普通对照"
            if p in dataset.high_performers:
                highlight.append(i)
            rows.append([group, p.id, (p.published_at or "")[:10],
                         T.truncate(T.first_line(p.text), 30),
                         p.metrics.likes if p.metrics.likes is not None else "-",
                         p.metrics.comments if p.metrics.comments is not None else "-",
                         p.metrics.total, f"{T.char_count(p.text)}字"])
        C.table(["分组", "ID", "发布日", "首句", "赞", "评论", "互动合计", "篇幅"], rows,
                aligns=["center", "left", "center", "left", "right", "right", "right", "right"],
                title="样本分组（依据平台真实互动数据）", highlight_rows=highlight)
        if dataset.posts and dataset.posts[0].metrics.missing_fields:
            C.warn("以下指标该平台公开接口不提供，已按'数据不可得'处理，未参与计算："
                   + "、".join(dataset.posts[0].metrics.missing_fields))

    # ---------------------------------------------------------------- Step 2
    def _step2(self, session: Session) -> None:
        if self.verbose:
            C.step(2, TOTAL_STEPS, "深度拆解与归因分析（Deep Analysis）")
            C.action("六维拆解（选题/Hook/结构节奏/信息密度/CTA/互动设计）→ 高低对比 → 公式沉淀")
        analysis = self.analyzer.analyze(session.dataset)
        session.analysis = analysis
        session.stage = Stage.ANALYZED
        self._flush_thoughts("分析思考过程")
        if self.verbose:
            self._print_dimension_table(session)
            self._print_variable_table(analysis)
            self._print_template(analysis)
        self._save(session)

    def _print_dimension_table(self, session: Session) -> None:
        dataset, analysis = session.dataset, session.analysis
        by_id = {p.id: p for p in dataset.posts}
        rows, highlight = [], []
        for i, pa in enumerate(analysis.post_analyses):
            post = by_id.get(pa.post_id)
            tag = "🔥高" if pa.group == "high" else "普通"
            if pa.group == "high":
                highlight.append(i)
            rows.append([tag, pa.post_id,
                         *[pa.dimensions[k].score for k, _ in
                           [("topic", 0), ("hook", 0), ("structure", 0),
                            ("density", 0), ("cta", 0), ("interaction", 0)]],
                         pa.viral_index,
                         post.metrics.total if post else "-"])
        C.table(["组", "ID", "选题", "Hook", "结构", "密度", "CTA", "互动", "综合指数", "真实互动"],
                rows, aligns=["center", "left"] + ["right"] * 8,
                title="六维拆解对比表（0-100 分，可复算）", highlight_rows=highlight)
        for pa in analysis.post_analyses:
            if pa.group == "high":
                C.bullet(f"{C.c(pa.post_id, 'bold')} {pa.one_line}", indent=4)
                for key in ("hook", "cta"):
                    d = pa.dimensions.get(key)
                    if d:
                        C.bullet(C.c(f"{d.name}：{d.insight} ｜ 证据：{T.truncate(d.evidence, 44)}",
                                     "gray"), indent=7, marker="↳")

    def _print_variable_table(self, analysis: AnalysisResult) -> None:
        shown = [v for v in analysis.variables if v.confidence != "噪声"][:7]
        C.table(["关键变量", "高表现组", "普通内容组", "差值", "置信度", "解释"],
                [[v.name, v.high_value, v.normal_value, v.delta, v.confidence,
                  T.truncate(v.explanation, 30)] for v in shown],
                aligns=["left", "right", "right", "right", "center", "left"],
                title="差异归因：到底是什么造成了数据分化",
                highlight_rows=[i for i, v in enumerate(shown) if v.confidence == "强因果"])
        noise = [v.name for v in analysis.variables if v.confidence == "噪声"]
        if noise:
            C.info(C.c("已排除的噪声变量（两组无显著差异）：" + "、".join(noise[:6]), "gray"))
        if analysis.rejected_hypotheses:
            for h in analysis.rejected_hypotheses[:3]:
                C.bullet(C.c("被数据否掉的猜想：" + h, "gray"), indent=4, marker="✗")
        C.blank()
        print("  " + C.c("核心洞察 ▸ ", "bold", "bright_magenta"))
        C.wrapped(C.c(analysis.core_insight, "bold"), indent=4)
        if analysis.explanatory_power:
            weak = analysis.explanatory_power.startswith("解释力弱")
            print("  " + C.c("解释力自评 ▸ ", "bold", "bright_red" if weak else "gray"))
            C.wrapped(C.c(analysis.explanatory_power, "yellow" if weak else "gray"), indent=4)

    def _print_template(self, analysis: AnalysisResult) -> None:
        tpl = analysis.template
        if not tpl:
            return
        C.blank()
        print("  " + C.c(f"公式沉淀 ▸ 《{tpl.name}》", "bold", "bright_green"))
        C.table(["#", "模块", "这一段要达成什么", "写法约束"],
                [[i, b.get("role", ""), b.get("goal", ""), b.get("rule", "")]
                 for i, b in enumerate(tpl.blocks, 1)],
                aligns=["center", "left", "left", "left"], max_col=40)
        C.kv("篇幅区间", tpl.length_range)
        C.kv("建议时段", tpl.publish_window)
        C.kv("发布前自检", " ｜ ".join(tpl.checklist[:3]))

    # ---------------------------------------------------------------- Step 3
    def _step3(self, session: Session, interactive: bool = True,
               reader: Optional[Callable[[str], str]] = None) -> None:
        if self.verbose:
            C.step(3, TOTAL_STEPS, "二次创作与人工确认（Creation & Human-in-the-loop）")
        feedback: Optional[str] = None
        previous: List[Draft] = []

        while True:
            if self.verbose:
                C.action(f"围绕同一核心洞察生成 3 条不同角度的原创候选内容"
                         f"{'（第 %d 轮修改）' % session.revision_round if session.revision_round else ''}")
            session.drafts = self.creator.create(session.analysis, n=3, feedback=feedback,
                                                previous=previous)
            session.stage = Stage.DRAFTED
            self._flush_thoughts("创作思考过程")
            self.gate.render_confirmation_sheet(session.dataset, session.analysis,
                                                session.drafts, session.id)
            session.stage = Stage.AWAITING_APPROVAL
            self._save(session)

            if not interactive:
                C.human_gate("工作流已停在人工确认环节（非交互模式）。\n"
                             f"请执行：python main.py resume --session {session.id} --decision 确认",
                             hint="确认 / 修改 / 取消")
                return

            decision, token, fb = self.gate.wait_for_decision(session.drafts, session.id, reader)
            if decision == DECISION_CONFIRM:
                session.approval = token
                session.stage = Stage.APPROVED
                self._save(session)
                return
            if decision == DECISION_ABORT:
                session.stage = Stage.ABORTED
                self._save(session)
                return
            # 修改轮次
            session.revision_round += 1
            session.feedback_history.append(fb)
            previous = list(session.drafts)
            feedback = fb or "换一批角度，加强开头冲突感与结尾互动装置"
            if session.revision_round > self.settings.max_revision_rounds:
                C.err(f"已达最大修改轮次 {self.settings.max_revision_rounds}，流程终止，未入库。")
                session.stage = Stage.ABORTED
                self._save(session)
                return

    # ---------------------------------------------------------------- Step 4
    def _step4(self, session: Session) -> None:
        if self.verbose:
            C.step(4, TOTAL_STEPS, "资产入库与记录（Asset Logging）")
            C.action(f"校验人工确认凭证 → 写入 {self.store.backend} 资产库 → 输出入库日志")
        records = self.store.commit(session.id, session.dataset, session.analysis,
                                    session.drafts, session.approval)
        session.asset_ids = [r["asset_id"] for r in records]
        session.stage = Stage.LOGGED
        self._flush_thoughts("入库思考过程")
        if self.verbose:
            C.blank()
            for r in records:
                print("  " + C.c(" LOG ", "on_green", "black", "bold") + " " +
                      C.c(f"内容已入库，ID: {r['asset_id']}，待后续追踪表现。", "bright_green", "bold"))
                C.bullet(C.c(f"角度：{r['angle']} ｜ 预测指数：{r['predicted_score']} ｜ "
                             f"确认人：{r['approved_by']} ｜ 凭证：{r['approval_digest'][:12]}…", "gray"),
                         indent=8, marker="·")
            C.blank()
            C.ok(f"共入库 {len(records)} 条，资产库：{getattr(self.store, 'path', self.store.backend)}")
            C.rule("工作流结束", "═", "green")
        self._save(session)

    # ================================================================ 续跑
    def resume(self, session_id: str, decision: str, feedback: str = "",
               interactive: bool = True,
               reader: Optional[Callable[[str], str]] = None) -> Session:
        session = self.load(session_id)
        if session.stage not in (Stage.AWAITING_APPROVAL, Stage.DRAFTED):
            raise RuntimeError(f"会话 {session_id} 当前状态为 {session.stage}，不在待确认状态")
        if self.verbose:
            C.banner("续跑：人工确认环节", f"会话 {session.id} · 当前状态 {session.stage}")
        from config.prompts import CONFIRM_ABORT, CONFIRM_ACCEPT, CONFIRM_REVISE

        raw = (decision or "").strip()
        head = raw.split()[0].lower() if raw else ""
        rest = raw[len(head):].strip()

        if head in CONFIRM_ABORT:
            session.stage = Stage.ABORTED
            self._save(session)
            C.err("人工取消，未写入任何内容。")
            return session
        if head in CONFIRM_ACCEPT:
            token = ApprovalToken(
                session_id=session.id, decision=DECISION_CONFIRM, operator=self.gate.operator,
                approved_at=datetime.now(timezone.utc).isoformat(),
                digest=ApprovalToken.make_digest(session.drafts),
                selected_ids=[d.id for d in HumanReviewGate._parse_selection(
                    rest, session.drafts)],
                note="通过 resume 命令确认")
            session.approval = token
            session.stage = Stage.APPROVED
            C.ok(f"人工确认已记录，凭证摘要 {token.digest[:12]}…")
            self._step4(session)
            return session
        if head in CONFIRM_REVISE:
            feedback = feedback or rest
            session.revision_round += 1
            session.feedback_history.append(feedback)
            session.drafts = self.creator.create(session.analysis, n=3, feedback=feedback,
                                                 previous=session.drafts)
            session.stage = Stage.AWAITING_APPROVAL
            self._flush_thoughts("修改轮次思考过程")
            self.gate.render_confirmation_sheet(session.dataset, session.analysis,
                                                session.drafts, session.id)
            self._save(session)
            if interactive:
                d, token, fb = self.gate.wait_for_decision(session.drafts, session.id, reader)
                if d == DECISION_CONFIRM:
                    session.approval = token
                    session.stage = Stage.APPROVED
                    self._step4(session)
            return session
        raise RuntimeError(f"无法识别的决策指令：{decision}（可用：确认 / 修改 / 取消）")

    # ================================================================ 持久化
    @staticmethod
    def session_path(session_id: str) -> Path:
        return Path(SESSION_DIR) / f"{session_id}.json"

    def _save(self, session: Session) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        p = self.session_path(session.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(session.dumps(), encoding="utf-8")

    def load(self, session_id: str) -> Session:
        p = self.session_path(session_id)
        if not p.exists():
            raise FileNotFoundError(f"找不到会话文件：{p}")
        return Session.from_dict(json.loads(p.read_text(encoding="utf-8")))
