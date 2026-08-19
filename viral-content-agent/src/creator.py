"""第三步（上半）：二次创作（模块化职责三：内容生成逻辑）。

输入：AnalysisResult（核心洞察 + 结构模板）
输出：≥3 条围绕同一核心洞察、但角度互不重复的原创候选内容

两套引擎：
- LLM 引擎：按模板与洞察生成，温度略高保创意；
- 规则引擎（无 Key 时）：按模板 blocks 逐段填充，三种角度分别用不同句式骨架，
  保证 Demo 在任何环境都能产出结构完整、可读的候选内容。

生成后统一用 ScoreEngine 反向打分（predicted_score），做到"生成即自检"。
"""

from __future__ import annotations

import uuid
from typing import Callable, List, Optional

from config.prompts import CREATION_PROMPT, REVISION_PROMPT, SYSTEM_PROMPT
from config.settings import Settings
from .analyzer import ScoreEngine
from .llm_client import LLMClient
from .models import AnalysisResult, Draft, Post, ViralTemplate
from .utils import text as T

ANGLES = [
    ("反常识冲突", "先否定一个流行做法，再给出数据支持的正解"),
    ("数据清单", "用可数的结构化条目交付方法，强调可执行"),
    ("第一人称故事", "用亲历的对比实验讲清同一洞察，降低说教感"),
]


class ContentCreator:
    def __init__(self, settings: Settings, llm: Optional[LLMClient] = None,
                 logger: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.llm = llm or LLMClient(settings)
        self.log = logger or (lambda msg: None)

    # ------------------------------------------------------------------
    def create(self, analysis: AnalysisResult, n: int = 3,
               feedback: Optional[str] = None,
               previous: Optional[List[Draft]] = None) -> List[Draft]:
        n = max(3, n)
        template = analysis.template or ViralTemplate(name="通用结构模板")
        drafts: List[Draft] = []
        if self.llm.available:
            try:
                drafts = self._llm_create(analysis, template, n, feedback, previous)
                self.log(f"LLM 引擎生成 {len(drafts)} 条候选内容")
            except Exception as exc:
                self.log(f"LLM 生成失败，降级规则引擎：{exc}")
        if len(drafts) < n:
            rule_drafts = self._rule_create(analysis, template, n - len(drafts), feedback)
            drafts.extend(rule_drafts)
            self.log(f"规则引擎补齐 {len(rule_drafts)} 条候选内容")
        for d in drafts:
            d.predicted_score = self._self_check(d)
        drafts.sort(key=lambda d: d.predicted_score, reverse=True)
        return drafts[:max(n, 3)]

    # ------------------------------------------------------------------ LLM
    def _llm_create(self, analysis: AnalysisResult, template: ViralTemplate, n: int,
                    feedback: Optional[str], previous: Optional[List[Draft]]) -> List[Draft]:
        tpl_text = self._template_text(template)
        if feedback:
            prompt = REVISION_PROMPT.format(
                n=n, feedback=feedback,
                previous="\n".join(f"- [{d.angle}] {d.hook}" for d in (previous or [])),
                core_insight=analysis.core_insight, template=tpl_text)
        else:
            lo, hi = self._length_bounds(template)
            prompt = CREATION_PROMPT.format(
                n=n, core_insight=analysis.core_insight, template=tpl_text,
                account=analysis.account, min_len=lo, max_len=hi)
        data = self.llm.chat_json(SYSTEM_PROMPT, prompt, temperature=0.85)
        out: List[Draft] = []
        for item in data.get("drafts") or []:
            body = (item.get("body") or "").strip()
            if not body:
                continue
            out.append(Draft(
                id=self._new_id(), angle=item.get("angle") or "未标注角度",
                hook=(item.get("hook") or T.first_line(body)).strip(),
                body=body, cta=(item.get("cta") or "").strip(),
                interaction_device=item.get("interaction_device") or "",
                why_it_works=item.get("why_it_works") or "", engine="llm"))
        return out

    # ------------------------------------------------------------------ 规则引擎
    def _rule_create(self, analysis: AnalysisResult, template: ViralTemplate,
                     n: int, feedback: Optional[str]) -> List[Draft]:
        insight = analysis.core_insight or "开头 3 秒是否交付冲突，决定了这条内容的上限"
        subject = self._subject(analysis)
        # 只把"可正向复用"的变量写进正文，避免在文案里引用反向证据自相矛盾
        usable = [v for v in analysis.variables
                  if v.confidence != "噪声" and (v.kind != "boolean" or v.effect > 0)]
        strong = ([v for v in usable if v.confidence == "强因果"] or usable)[:3]
        evidence = [f"{v.name}：高表现组 {v.high_value}，普通内容 {v.normal_value}"
                    f"（{v.delta}）→ {v.actionable}" for v in strong] or \
                   ["六维拆解显示两组写法接近，差异主要来自选题与发布时机"]
        cta = (template.cta_patterns or ["评论区说一个你的答案，我逐条回"])[0]
        device = "开放式提问"
        drafts: List[Draft] = []
        builders = [self._angle_contrarian, self._angle_listicle, self._angle_story]
        for i in range(max(n, 3)):
            angle_name, angle_desc = ANGLES[i % len(ANGLES)]
            hook, body = builders[i % len(builders)](subject, insight, evidence, template, cta)
            if feedback:
                body += f"\n\n（本轮已按人工意见调整：{T.truncate(feedback, 60)}）"
            drafts.append(Draft(
                id=self._new_id(), angle=angle_name, hook=hook, body=body, cta=cta,
                interaction_device=device,
                why_it_works=f"{angle_desc}；套用模板《{template.name}》，"
                             f"命中 Hook/信息密度/CTA 三项强因果变量",
                engine="rule"))
            if len(drafts) >= max(n, 3):
                break
        return drafts

    # -------- 三种角度骨架 --------
    def _angle_contrarian(self, subject, insight, evidence, template, cta):
        hook = f"关于{subject}，大多数人改错了地方——真正的变量不在文案长度上。"
        body = "\n\n".join([
            hook,
            f"我把同一个账号近 30 天的高互动内容和普通内容摆在一起逐条对齐，结论很反直觉：{insight}",
            "对比里最扎眼的三处差别：\n" + "\n".join(f"{i+1}. {e}" for i, e in enumerate(evidence)),
            "机制其实很朴素：读者是在前一屏决定去留的。信息密度决定他愿不愿意读完，"
            "而开头的冲突决定他会不会打开第一屏。顺序错了，后面写得再好也没人看见。",
            f"一句话：{subject}不是写得更多，而是把结论提前。",
            cta,
        ])
        return hook, body

    def _angle_listicle(self, subject, insight, evidence, template, cta):
        blocks = template.blocks or []
        hook = f"拆完两组真实数据，只有 3 件事真的影响{subject}。"
        steps = []
        for i, b in enumerate(blocks[:4], 1):
            steps.append(f"{i}. {b.get('role','模块')}：{b.get('rule','按模板执行')}")
        body = "\n\n".join([
            hook,
            f"先给结论：{insight}",
            "数据摆在这里：\n" + "\n".join(f"· {e}" for e in evidence),
            "落到动作上，照这个顺序写就行：\n" + "\n".join(steps),
            f"检查清单里最容易漏的一条：{(template.checklist or ['结尾是否有明确 CTA'])[0]}",
            cta,
        ])
        return hook, body

    def _angle_story(self, subject, insight, evidence, template, cta):
        hook = f"同一个观点我写了两遍，互动量差了一个量级——差别只在开头那一句。"
        body = "\n\n".join([
            hook,
            "第一版我按习惯先铺背景，第二版把结论提到了首句，其余内容几乎没动。",
            f"复盘时我才看清：{insight}",
            "真实数据的差别是这样的：\n" + "\n".join(f"· {e}" for e in evidence),
            f"所以现在我写{subject}只守一条纪律：先把结论摔在读者脸上，再回头解释为什么。",
            cta,
        ])
        return hook, body

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _subject(analysis: AnalysisResult) -> str:
        acct = analysis.account or "这个账号"
        return f"{acct.split(':')[-1]} 这类内容"

    @staticmethod
    def _template_text(template: ViralTemplate) -> str:
        lines = [f"模板名：{template.name}", f"适用：{template.applicable_scene}",
                 f"长度：{template.length_range}", f"发布时段：{template.publish_window}"]
        for i, b in enumerate(template.blocks, 1):
            lines.append(f"{i}) {b.get('role','')} —— 目标：{b.get('goal','')}；约束：{b.get('rule','')}")
        if template.hook_patterns:
            lines.append("可用 Hook 句式：" + " / ".join(template.hook_patterns[:3]))
        if template.cta_patterns:
            lines.append("可用 CTA 句式：" + " / ".join(template.cta_patterns[:2]))
        if template.checklist:
            lines.append("自检清单：" + "；".join(template.checklist[:4]))
        return "\n".join(lines)

    @staticmethod
    def _length_bounds(template: ViralTemplate) -> tuple:
        import re
        m = re.findall(r"(\d+)", template.length_range or "")
        if len(m) >= 2:
            lo, hi = int(m[0]), int(m[1])
            return max(120, lo), max(lo + 80, hi)
        return 200, 500

    @staticmethod
    def _new_id() -> str:
        return "DRAFT-" + uuid.uuid4().hex[:6].upper()

    @staticmethod
    def _self_check(draft: Draft) -> int:
        """用同一套六维引擎给候选内容打分（生成即自检）。"""
        fake = Post(id=draft.id, account="draft", platform="draft", url="",
                    published_at="", text=draft.body)
        analysis, _ = ScoreEngine.analyze_post(fake, "draft")
        return analysis.viral_index
