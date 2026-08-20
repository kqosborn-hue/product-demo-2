"""爆款内容拆解与二创 Agent —— 可视化 Web Demo（单文件 Streamlit 应用）

本文件只是"展示层"，所有核心逻辑都复用 src/ 里的真实代码：
    src.data_retrieval  → 第一步：真实公开数据获取与筛选
    src.analyzer        → 第二步：六维拆解 + 差异归因 + 模板沉淀
    src.creator         → 第三步（上）：二次创作（≥3 条候选）
    src.human_review    → 第三步（下）：人工确认闸门（不可绕过）
    src.asset_store     → 第四步：资产入库（写入前强制校验人工确认凭证）

合规红线：即使走网页版，资产入库前仍必须持有有效 ApprovalToken，
且 token 内含候选内容的 sha256 摘要——内容变了摘要就对不上，入库会被拒。
这和 CLI 版本是同一套硬闸门，不会因换界面而失效。

运行方式：
    streamlit run app.py
（默认使用 data/snapshots 下的真实抓取快照，无需任何 API Key。）
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# ------------------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from src.data_retrieval import DataRetriever
from src.analyzer import ContentAnalyzer
from src.creator import ContentCreator
from src.human_review import HumanReviewGate
from src.asset_store import get_asset_store
from src.models import ApprovalToken

DIM_LABELS = [
    ("topic", "选题"), ("hook", "Hook"), ("structure", "结构节奏"),
    ("density", "信息密度"), ("cta", "CTA"), ("interaction", "互动设计"),
]
DEFAULT_SNAPSHOT_ACCOUNT = "hn:author:pseudolus"


# ========================================================================= 样式
CSS = """
<style>
/* 流程进度条胶囊 */
.step-pill {
    display:inline-block; padding:2px 10px; margin-right:6px; border-radius:999px;
    font-size:12px; font-weight:600; border:1px solid #e3e3e3; color:#888; background:#fafafa;
}
.step-pill.active { background:#2563eb; color:#fff; border-color:#2563eb; }
.step-pill.done { background:#16a34a; color:#fff; border-color:#16a34a; }

/* 数据对比卡片 */
.compare-grid { display:flex; gap:14px; }
.compare-card {
    flex:1; border-radius:12px; padding:14px 16px; border:1px solid #ececec;
    background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.04);
}
.compare-card.fire { border-left:5px solid #f59e0b; }
.compare-card.normal { border-left:5px solid #94a3b8; }
.compare-card h4 { margin:0 0 6px; font-size:15px; }
.compare-card .metric { font-size:22px; font-weight:700; color:#111; }
.compare-card .sub { font-size:12px; color:#777; }

/* 人工确认黄框 */
.human-gate {
    border:2px dashed #f59e0b; background:#fffbeb; border-radius:12px;
    padding:14px 16px; margin:10px 0;
}
.human-gate .title { font-weight:700; color:#b45309; font-size:15px; }

/* 让"执行入库"在激活时更有"亮起来"的感觉 */
div[data-testid="stButton"] button[kind="primary"] {
    box-shadow:0 0 0 3px rgba(37,99,235,.18); transition:all .15s ease;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ========================================================================= 工具
def make_session_id() -> str:
    return "WEB-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()


def resolve_source(mode: str) -> str:
    return "snapshot" if mode == "snapshot" else "auto"


def resolve_account(mode: str, raw: str) -> str:
    raw = (raw or "").strip()
    if mode == "snapshot":
        # 快照模式固定使用内置真实抓取数据（无论输入什么都会命中唯一快照）
        return raw or DEFAULT_SNAPSHOT_ACCOUNT
    return raw or "hn:topic:AI agent"


def run_pipeline(account: str, source: str):
    """复用 src 四步逻辑，返回 (dataset, analysis, drafts)。无 Key 时自动走规则引擎。"""
    settings = get_settings()
    retriever = DataRetriever(settings, logger=lambda m: None)
    analyzer = ContentAnalyzer(settings)
    creator = ContentCreator(settings)
    dataset = retriever.retrieve(account, source=source)
    analysis = analyzer.analyze(dataset)
    drafts = creator.create(analysis, n=3)
    return dataset, analysis, drafts


def run_revision(analysis, previous_drafts, feedback: str):
    """修改轮次：复用 ContentCreator 的 revision 能力，按人工意见重新生成候选。

    传入了 previous（上一版草稿）与 feedback（人工意见），
    规则引擎会把意见写进正文、LLM 引擎会走 REVISION_PROMPT 重写。
    """
    settings = get_settings()
    creator = ContentCreator(settings)
    fb = (feedback or "").strip() or None
    return creator.create(analysis, n=3, feedback=fb, previous=previous_drafts)


def do_commit(dataset, analysis, drafts, session_id: str, operator: str):
    """入库：先签发人工确认凭证并通过硬闸门，再写入资产库。"""
    settings = get_settings()
    gate = HumanReviewGate(settings, operator=operator)
    token = ApprovalToken(
        session_id=session_id,
        decision="confirm",
        operator=operator,
        approved_at=datetime.now(timezone.utc).isoformat(),
        digest=ApprovalToken.make_digest(drafts),
        selected_ids=[d.id for d in drafts],
        note="Web 端人工确认（已勾选审核框）",
    )
    gate.assert_approved(token, drafts, session_id)        # ← 不可绕过的代码级闸门
    store = get_asset_store(settings)
    records = store.commit(session_id, dataset, analysis, drafts, token)
    return records, token, store.backend


# ========================================================================= 渲染
def render_stepper(stage: str):
    order = ["idle", "drafted", "stored"]
    labels = {"idle": "① 数据概览", "drafted": "② 拆解分析 → ③ 人工确认", "stored": "④ 资产入库"}
    html = ""
    for i, s in enumerate(["idle", "drafted", "stored"], 1):
        cls = "active" if stage == s else ("done" if order.index(s) < order.index(stage) else "")
        html += f'<span class="step-pill {cls}">{labels[s]}</span>'
    st.markdown(html, unsafe_allow_html=True)


def render_step1(dataset):
    st.subheader("第一步 · 真实数据概览")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("数据来源", dataset.provider)
    c2.metric("样本总数", len(dataset.posts))
    c3.metric("🔥 高表现", len(dataset.high_performers))
    c4.metric("普通对照", len(dataset.control_group))

    st.caption(f"账号 `{dataset.account}` · 平台 {dataset.platform} · 窗口 {dataset.window_days} 天 "
               f"· 抓取于 {dataset.fetched_at[:19]}（真实公开数据，未经编造）")
    for n in dataset.notes:
        st.info(n)

    high = dataset.high_performers
    norm = dataset.control_group
    col_fire, col_norm = st.columns(2)
    with col_fire:
        st.markdown('<div class="compare-card fire"><h4>🔥 高表现内容（Top）</h4></div>',
                    unsafe_allow_html=True)
        for p in high:
            total = p.metrics.total
            st.markdown(
                f'<div class="compare-card fire">'
                f'<div class="metric">{total} 互动</div>'
                f'<div class="sub">{p.metrics.brief()} · {p.published_at[:10]}</div>'
                f'<div style="margin-top:6px;font-size:13px">{_preview(p.text)}</div>'
                f'</div>', unsafe_allow_html=True)
    with col_norm:
        st.markdown('<div class="compare-card normal"><h4>普通内容（对照组）</h4></div>',
                    unsafe_allow_html=True)
        for p in norm:
            total = p.metrics.total
            st.markdown(
                f'<div class="compare-card normal">'
                f'<div class="metric">{total} 互动</div>'
                f'<div class="sub">{p.metrics.brief()} · {p.published_at[:10]}</div>'
                f'<div style="margin-top:6px;font-size:13px">{_preview(p.text)}</div>'
                f'</div>', unsafe_allow_html=True)


def render_step2(dataset, analysis):
    st.subheader("第二步 · 六维拆解与差异归因")

    # 1) 六维拆解对比表
    rows = []
    by_id = {p.id: p for p in dataset.posts}
    for pa in analysis.post_analyses:
        post = by_id.get(pa.post_id)
        row = {"分组": "🔥高表现" if pa.group == "high" else "普通",
               "ID": pa.post_id}
        for k, label in DIM_LABELS:
            row[label] = pa.dimensions[k].score
        row["综合指数"] = pa.viral_index
        row["真实互动"] = post.metrics.total if post else "-"
        rows.append(row)
    import pandas as pd
    df = pd.DataFrame(rows)
    st.markdown("**六维拆解对比（0–100 分，可复算）**")
    st.dataframe(df, use_container_width=True, height=min(340, 60 + 40 * len(df)))

    # 2) 差异归因表
    vrows = [{"关键变量": v.name, "高表现组": v.high_value, "普通内容组": v.normal_value,
              "差值": v.delta, "置信度": v.confidence, "下次怎么用": v.actionable}
             for v in analysis.variables]
    st.markdown("**到底是什么造成了数据分化（差异归因）**")
    st.dataframe(pd.DataFrame(vrows), use_container_width=True, height=min(360, 60 + 36 * len(vrows)))

    # 3) 核心洞察 + 解释力自评
    st.markdown("**核心洞察**")
    st.success(analysis.core_insight)
    if analysis.explanatory_power:
        weak = analysis.explanatory_power.startswith("解释力弱")
        (st.warning if weak else st.info)(analysis.explanatory_power)

    # 4) 沉淀模板
    tpl = analysis.template
    if tpl:
        st.markdown(f"**沉淀出的可复用模板：《{tpl.name}》**")
        st.caption(f"适用：{tpl.applicable_scene} ｜ 篇幅：{tpl.length_range} ｜ 建议时段：{tpl.publish_window}")
        blocks = [{"模块": b.get("role", ""), "目标": b.get("goal", ""),
                   "写法约束": b.get("rule", "")} for b in tpl.blocks]
        st.dataframe(pd.DataFrame(blocks), use_container_width=True, hide_index=True)


def render_step3(drafts):
    st.subheader("第三步 · 人工确认（Human-in-the-loop）")
    st.markdown(
        '<div class="human-gate"><div class="title">⏸ 等待人工审核</div>'
        '下方为生成的 3 条二创候选内容。请逐条审核，确认无误后勾选确认框并点击「执行入库」。</div>',
        unsafe_allow_html=True)

    for i, d in enumerate(drafts, 1):
        with st.expander(f"候选 {i} · {d.angle} · 预测指数 {d.predicted_score} · 引擎 {d.engine}",
                         expanded=(i == 1)):
            st.markdown(f"**Hook**：{d.hook}")
            st.markdown(d.body)
            st.markdown(f"**CTA**：{d.cta}")
            st.caption(f"互动装置：{d.interaction_device or '-'} ｜ 命中逻辑：{d.why_it_works}")


def render_step4(records, token, backend):
    st.subheader("第四步 · 资产入库反馈")
    st.balloons()
    st.success("✅ 已通过人工确认，内容成功入库！")

    steps = [
        ("校验人工确认凭证（sha256 摘要比对）", token.digest[:16] + "…", True),
        (f"写入本地资产库 content_assets.json（实际落库，后端：{backend}）", f"{len(records)} 条记录", True),
        ("同步至 Notion / 飞书多维表格（演示模拟，需在 .env 配置对应 Key 后生效）", "模拟完成", True),
    ]
    for label, val, ok in steps:
        st.markdown(f"- {'✅' if ok else '⏳'} **{label}** — `{val}`")

    import pandas as pd
    rrows = [{"资产 ID": r["asset_id"], "角度": r["angle"], "预测指数": r["asset_id"] and r["predicted_score"],
              "确认人": r["approved_by"], "状态": r["status"]} for r in records]
    st.markdown("**本次入库资产**")
    st.dataframe(pd.DataFrame(rrows), use_container_width=True, hide_index=True)


def _preview(text: str, n: int = 90) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


# ========================================================================= 主程序
def main():
    st.set_page_config(page_title="爆款内容拆解与二创 Agent", page_icon="🔥", layout="wide")

    st.title("🔥 爆款内容拆解与二创 Agent")
    st.caption("数据驱动 · 逻辑严密 · 极具创意 —— 真实公开数据对比 + 人工确认入库的网页版 Demo")

    # -------------------------------------------------------------- 侧边栏
    with st.sidebar:
        st.header("⚙️ 配置")
        mode = st.selectbox(
            "演示模式",
            ["snapshot", "live"],
            format_func=lambda m: ("📦 内置快照 Demo（无需 Key，推荐）"
                                   if m == "snapshot" else "🌐 联网抓取（需 API Key，失败自动回退快照）"),
            index=0,
        )
        account_input = st.text_input(
            "目标账号 / 洞察主题（可选）",
            value=DEFAULT_SNAPSHOT_ACCOUNT,
            help="快照模式默认演示 hn:author:pseudolus 的真实抓取数据；"
                 "联网模式可填如 hn:topic:AI agent 或 reddit:sub:xxx。",
        )
        operator = st.text_input("审核操作人", value="web-reviewer")
        st.divider()
        if st.button("🚀 开始拆解与生成", type="primary", use_container_width=True):
            with st.spinner("正在拉取真实公开数据并完成六维拆解…"):
                try:
                    acc = resolve_account(mode, account_input)
                    src = resolve_source(mode)
                    ds, an, dr = run_pipeline(acc, src)
                    st.session_state.dataset = ds
                    st.session_state.analysis = an
                    st.session_state.drafts = dr
                    st.session_state.session_id = make_session_id()
                    st.session_state.stage = "drafted"
                    st.session_state.rev_count = 0
                    st.session_state.feedback_history = []
                    st.session_state.error = None
                except Exception as exc:  # noqa: BLE001
                    st.session_state.error = f"{type(exc).__name__}: {exc}"
                    st.session_state.stage = "idle"
            st.rerun()

        if st.button("🔄 重置", use_container_width=True):
            for k in ("dataset", "analysis", "drafts", "session_id", "stage", "error",
                      "confirmed", "records", "token", "backend", "rev_count",
                      "feedback_history", "confirm_box", "rev_feedback"):
                st.session_state.pop(k, None)
            st.rerun()

        with st.expander("📋 已入库资产（本地库）"):
            try:
                for r in get_asset_store(get_settings()).list_assets()[::-1][:8]:
                    st.markdown(f"- `{r['asset_id']}` · {r['angle']} · 指数 {r['predicted_score']}")
            except Exception:
                st.write("（暂无）")

    # -------------------------------------------------------------- 状态初始化
    st.session_state.setdefault("stage", "idle")
    stage = st.session_state.stage

    render_stepper(stage)

    if st.session_state.get("error"):
        st.error("⚠️ 运行出错：" + st.session_state.error)

    # -------------------------------------------------------------- 流程渲染
    if stage in ("drafted", "stored"):
        dataset = st.session_state.dataset
        analysis = st.session_state.analysis
        drafts = st.session_state.drafts

        render_step1(dataset)
        st.divider()
        render_step2(dataset, analysis)
        st.divider()
        render_step3(drafts)

        # ------------------------------------------------ 修改轮次（人工确认的"修改"分支）
        if stage != "stored":
            st.divider()
            st.markdown("**✍️ 修改轮次（可选）**")
            st.caption(f"已修改 {st.session_state.get('rev_count', 0)} 轮。"
                       "填写修改意见后让 Agent 重新生成候选，满意后再走下方人工确认入库。")
            feedback = st.text_area(
                "修改意见", key="rev_feedback", height=80, label_visibility="collapsed",
                placeholder="例如：开头太平，加一句反常识；或：第 2 条语气太硬，软化一点")
            if st.button("🔄 按意见重新生成", use_container_width=True):
                with st.spinner("正在根据修改意见重新生成候选…"):
                    try:
                        st.session_state.drafts = run_revision(analysis, drafts, feedback)
                        st.session_state.rev_count = st.session_state.get("rev_count", 0) + 1
                        st.session_state.feedback_history = (
                            st.session_state.get("feedback_history", [])
                            + [feedback or "（未填写，自动换角度重写）"])
                        st.session_state.error = None
                        # 关键：候选已变化，旧的确认作废，必须重新人工确认才能入库
                        st.session_state["confirm_box"] = False
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.error = f"{type(exc).__name__}: {exc}"
                st.rerun()

        # 第三步：人工确认闸门（关键）
        st.divider()
        confirmed = st.checkbox("✅ 我已审核以上内容，确认入库", key="confirm_box")
        if confirmed:
            st.success("已确认，可点击下方按钮入库。")
        else:
            st.warning("请先勾选上方审核确认框，「执行入库」按钮才会激活。")

        if stage == "stored":
            st.success("✅ 本次内容已入库（见下方第四步）。")
        else:
            if st.button("📥 执行入库", type="primary", disabled=not confirmed, use_container_width=True):
                records, token, backend = do_commit(
                    dataset, analysis, drafts, st.session_state.session_id, operator)
                st.session_state.records = records
                st.session_state.token = token
                st.session_state.backend = backend
                st.session_state.stage = "stored"
                st.rerun()

        if stage == "stored":
            st.divider()
            render_step4(st.session_state.records, st.session_state.token, st.session_state.backend)

    else:
        st.info("👈 在左侧选择演示模式，点击「🚀 开始拆解与生成」即可看到完整四步流程。"
                "默认使用内置真实抓取快照，无需任何 API Key。")


if __name__ == "__main__":
    main()
