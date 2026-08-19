"""第二步：深度拆解与归因分析（模块化职责二：数据分析逻辑）。

三件事：
    A. 六维拆解   ScoreEngine.analyze_post()  —— 选题/Hook/结构节奏/信息密度/CTA/互动设计
    B. 差异对比   ContentAnalyzer.diff()      —— 高表现组 vs 普通对照组的可控变量差值
    C. 公式沉淀   ContentAnalyzer.distill()   —— 输出可复用的"爆款内容结构模板"

规则引擎先算出可复算的量化事实，LLM（若配置）只做解释与润色，
避免"模型一句话定结论"的不可验证归因。
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

from config.prompts import (ANALYSIS_PROMPT, DIFF_PROMPT, DIMENSIONS,
                            SYSTEM_PROMPT, TEMPLATE_PROMPT)
from config.settings import Settings
from .llm_client import LLMClient, LLMError
from .models import (AnalysisResult, Dataset, DimensionScore, Post, PostAnalysis,
                     VariableDiff, ViralTemplate)
from .utils import text as T


# ======================================================================
# A. 六维打分引擎（纯规则、可复算）
# ======================================================================
class ScoreEngine:
    @staticmethod
    def topic(f: Dict, post: Post) -> DimensionScore:
        hits, score = [], 40
        for name, weight, pattern in T.TOPIC_SIGNALS:
            if pattern.search(post.text or ""):
                hits.append(name)
                score += weight
        if f["has_number"]:
            score += 6
            hits.append("含具体数字")
        score = min(100, score)
        insight = ("选题命中 " + "、".join(hits) + " 类需求信号") if hits else \
            "选题缺少明确的痛点/利益/争议信号，受众没有点进来的动机"
        return DimensionScore("topic", "选题", score, insight,
                              T.truncate(T.first_line(post.text), 46))

    @staticmethod
    def hook(f: Dict, post: Post) -> DimensionScore:
        score = f["hook_base"]
        hl = f["hook_len"]
        if 8 <= hl <= 42:
            score += 8                      # 一屏可读完
        elif hl > 80:
            score -= 12                     # 开头太长，划走风险高
        if f["has_number"] and f["hook_type"] in ("数字清单型", "结果前置型"):
            score += 4
        score = max(10, min(100, score))
        return DimensionScore("hook", "Hook（开头）", score,
                              f"{f['hook_type']}，首句 {hl} 字",
                              f["hook_evidence"])

    @staticmethod
    def structure(f: Dict, post: Post) -> DimensionScore:
        n = f["paragraph_count"]
        score = 50
        if 3 <= n <= 8:
            score += 24
        elif n == 2:
            score += 8
        elif n > 12:
            score -= 8
        if 8 <= f["avg_sentence_len"] <= 34:
            score += 14                     # 句长适中，节奏跟得上
        if "论据/清单" in f["structure_blocks"]:
            score += 8
        if "收束金句" in f["structure_blocks"]:
            score += 6
        score = max(10, min(100, score))
        return DimensionScore("structure", "结构节奏", score,
                              f"{n} 段 / 平均句长 {f['avg_sentence_len']} 字 / 走向：" +
                              "→".join(f["structure_blocks"][:5]),
                              " → ".join(f["structure_blocks"][:5]))

    @staticmethod
    def density(f: Dict, post: Post) -> DimensionScore:
        d = f["info_density"]
        if d >= 9:
            score, note = 92, "信息密度高，几乎没有废话"
        elif d >= 6:
            score, note = 80, "信息密度良好"
        elif d >= 3.5:
            score, note = 62, "信息密度中等，可再压缩铺垫"
        elif d > 0:
            score, note = 42, "信息稀薄，读者拿不到可带走的干货"
        else:
            score, note = 25, "几乎没有可提取的信息点"
        if f["char_len"] < 30:
            score = min(score, 55)
            note += "（正文过短，样本本身信息量有限）"
        return DimensionScore("density", "信息密度", score, note,
                              f"{f['info_points']} 个信息点 / {f['char_len']} 字 = {d}/百字")

    @staticmethod
    def cta(f: Dict, post: Post) -> DimensionScore:
        score = f["cta_base"]
        if f["cta_type"] == "无明确 CTA":
            insight = "结尾没有行动指令，互动全靠读者自发，转化漏斗直接断裂"
        else:
            insight = f"{f['cta_type']}，动作明确"
        return DimensionScore("cta", "CTA（行动号召）", max(10, min(100, score)),
                              insight, f["cta_evidence"])

    @staticmethod
    def interaction(f: Dict, post: Post) -> DimensionScore:
        devices: List[str] = f["interaction_devices"]
        score = 30 + min(50, len(devices) * 16)
        if "开放式提问" in devices:
            score += 10
        if "二选一/站队" in devices or "投票/打分" in devices:
            score += 8
        if f["hashtag_count"] > 0:
            score += 4
        score = max(10, min(100, score))
        insight = ("互动装置：" + "、".join(devices)) if devices else \
            "没有任何互动装置，评论区缺少发言入口"
        return DimensionScore("interaction", "互动设计", score, insight,
                              f"装置 {len(devices)} 个 / 话题标签 {f['hashtag_count']} 个")

    @classmethod
    def analyze_post(cls, post: Post, group: str) -> Tuple[PostAnalysis, Dict]:
        f = T.extract_features(post.text, post.published_dt)
        dims = {
            "topic": cls.topic(f, post),
            "hook": cls.hook(f, post),
            "structure": cls.structure(f, post),
            "density": cls.density(f, post),
            "cta": cls.cta(f, post),
            "interaction": cls.interaction(f, post),
        }
        analysis = PostAnalysis(post_id=post.id, group=group, dimensions=dims)
        strongest = max(dims.values(), key=lambda d: d.score)
        weakest = min(dims.values(), key=lambda d: d.score)
        analysis.one_line = f"胜负手在【{strongest.name}】({strongest.score}分)，短板是【{weakest.name}】({weakest.score}分)"
        return analysis, f


# ======================================================================
# B/C. 对比归因 + 模板沉淀
# ======================================================================
VARIABLE_SPECS: List[Tuple[str, str, str, str]] = [
    # (变量名, 特征key, 类型, 单位)
    ("Hook 类型", "hook_type", "categorical", ""),
    ("首句字数", "hook_len", "numeric", "字"),
    ("正文字数", "char_len", "numeric", "字"),
    ("段落数", "paragraph_count", "numeric", "段"),
    ("信息密度", "info_density", "numeric", "点/百字"),
    ("是否含数字", "has_number", "boolean", ""),
    ("CTA 类型", "cta_type", "categorical", ""),
    ("互动装置数", "interaction_count", "numeric", "个"),
    ("话题标签数", "hashtag_count", "numeric", "个"),
    ("发布时段", "publish_slot", "categorical", ""),
    ("发布星期", "weekday", "categorical", ""),
    ("平均句长", "avg_sentence_len", "numeric", "字"),
]


class ContentAnalyzer:
    def __init__(self, settings: Settings, llm: Optional[LLMClient] = None,
                 logger: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.llm = llm or LLMClient(settings)
        self.log = logger or (lambda msg: None)
        self.features: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    def analyze(self, dataset: Dataset) -> AnalysisResult:
        result = AnalysisResult(account=dataset.account)
        engines = set()

        for post in dataset.high_performers:
            pa, f = ScoreEngine.analyze_post(post, "high")
            self.features[post.id] = f
            self._llm_enrich(pa, post, dataset, "高表现内容", f) and engines.add("llm")
            result.post_analyses.append(pa)
            self.log(f"六维拆解完成 [高表现] {post.id} → 综合指数 {pa.viral_index}")

        for post in dataset.control_group:
            pa, f = ScoreEngine.analyze_post(post, "normal")
            self.features[post.id] = f
            result.post_analyses.append(pa)
            self.log(f"六维拆解完成 [对照组] {post.id} → 综合指数 {pa.viral_index}")

        result.variables = self.diff(dataset)
        self.log(f"差异归因完成，识别出 {len(result.variables)} 个关键变量")
        result.core_insight = self._core_insight(dataset, result)
        result.explanatory_power = self._explanatory_power(dataset, result)
        self.log("解释力自评：" + result.explanatory_power[:60] + "…")
        self._llm_diff(dataset, result) and engines.add("llm")
        result.template = self.distill(dataset, result)
        engines.add("rule")
        result.engine = "+".join(sorted(engines))
        return result

    # ------------------------------------------------------------------ 差异对比
    def diff(self, dataset: Dataset) -> List[VariableDiff]:
        high_f = [self.features[p.id] for p in dataset.high_performers if p.id in self.features]
        norm_f = [self.features[p.id] for p in dataset.control_group if p.id in self.features]
        if not high_f or not norm_f:
            return []
        out: List[VariableDiff] = []
        for name, key, kind, unit in VARIABLE_SPECS:
            if kind == "numeric":
                hv = statistics.mean([float(f[key]) for f in high_f])
                nv = statistics.mean([float(f[key]) for f in norm_f])
                base = max(abs(hv), abs(nv), 1e-6)
                effect = (hv - nv) / base
                delta = f"{hv - nv:+.1f}{unit}"
                if abs(effect) >= 0.35:
                    conf, why = "强因果", "两组均值差异超过 35%，是可控写法差异"
                elif abs(effect) >= 0.15:
                    conf, why = "疑似相关", "存在中等差异，建议 A/B 复验"
                else:
                    conf, why = "噪声", "差异过小，不足以解释数据分化"
                out.append(VariableDiff(name, kind, f"{hv:.1f}{unit}", f"{nv:.1f}{unit}",
                                        delta, round(effect, 3), conf, why,
                                        self._actionable(key, hv, nv, unit)))
            elif kind == "boolean":
                hv = sum(1 for f in high_f if f[key]) / len(high_f)
                nv = sum(1 for f in norm_f if f[key]) / len(norm_f)
                effect = hv - nv
                conf = "强因果" if abs(effect) >= 0.5 else ("疑似相关" if abs(effect) >= 0.25 else "噪声")
                direction = "更多出现在高表现组" if effect > 0 else (
                    "反而更多出现在普通组" if effect < 0 else "两组一致")
                out.append(VariableDiff(name, kind, f"{hv*100:.0f}% 命中", f"{nv*100:.0f}% 命中",
                                        f"{effect*100:+.0f}pp", round(effect, 3), conf,
                                        f"该特征{direction}（命中率差 {effect*100:+.0f} 个百分点）",
                                        self._actionable(key, hv, nv)))
            else:
                hc = Counter(f[key] for f in high_f)
                nc = Counter(f[key] for f in norm_f)
                hv, nv = hc.most_common(1)[0][0], nc.most_common(1)[0][0]
                same = hv == nv
                share = hc.most_common(1)[0][1] / len(high_f)
                effect = 0.0 if same else round(share, 3)
                conf = "噪声" if same else ("强因果" if share >= 0.66 else "疑似相关")
                out.append(VariableDiff(name, kind, f"{hv}（{share*100:.0f}%）",
                                        f"{nv}", "一致" if same else "不同",
                                        effect, conf,
                                        "两组主导取值一致，不构成差异来源" if same
                                        else f"高表现组集中使用「{hv}」，对照组主要是「{nv}」",
                                        self._actionable(key, hv, nv)))
        out.sort(key=lambda v: abs(v.effect), reverse=True)
        return out

    @staticmethod
    def _actionable(key: str, hv, nv, unit: str = "") -> str:
        """方向感知的可执行建议：结论必须跟数据方向一致，不能给反向指令。"""
        if key in ("publish_slot", "weekday"):
            return f"优先在「{hv}」发布" if hv != nv else f"两组都集中在「{hv}」，不是差异来源"
        if key == "hook_type":
            return f"开头套用「{hv}」句式" if hv != nv else f"两组都用「{hv}」，需从选题/时段找差异"
        if key == "cta_type":
            if hv == nv:
                return f"两组 CTA 都是「{hv}」，若为'无明确 CTA'则是可直接吃到的增量空间"
            return f"结尾换成「{hv}」"
        if key == "has_number":
            if hv > nv:
                return "正文/开头放入具体数字与量级"
            if hv < nv:
                return "数字堆砌并未带来增益，别为凑数字牺牲可读性"
            return "两组都含数字，不是差异来源"
        try:
            hi, lo = float(hv), float(nv)
        except (TypeError, ValueError):
            return "对齐高表现组该变量的取值"
        verb = "提高到" if hi > lo else ("压缩到" if hi < lo else "保持在")
        targets = {
            "hook_len": f"把首句{verb} {hi:.0f}{unit} 左右",
            "char_len": f"正文篇幅{verb} {hi:.0f}{unit} 量级，不要为凑长度加铺垫",
            "paragraph_count": f"段落数{verb} {hi:.0f} 段，按此切节奏",
            "info_density": f"信息密度{verb} {hi:.1f} 点/百字",
            "interaction_count": f"互动装置数量{verb} {hi:.0f} 个",
            "hashtag_count": f"话题标签数{verb} {hi:.0f} 个",
            "avg_sentence_len": f"平均句长{verb} {hi:.0f}{unit}（{'拆长句' if hi < lo else '适度合并短句'}）",
        }
        return targets.get(key, f"该变量{verb} {hi:.1f}{unit}")

    # ------------------------------------------------------------------ 核心洞察
    def _core_insight(self, dataset: Dataset, result: AnalysisResult) -> str:
        strong = [v for v in result.variables if v.confidence == "强因果"][:3]
        if not strong:
            strong = [v for v in result.variables if v.confidence == "疑似相关"][:3]
        if not strong:
            return (f"在 {dataset.account} 的样本里，可控写法变量两组几乎一致，"
                    f"互动差异更可能来自选题领域本身与曝光时机，不宜归因到文案技巧。")
        names = "、".join(v.name for v in strong)
        actions = "；".join(v.actionable for v in strong[:2])
        top = dataset.high_performers[0] if dataset.high_performers else None
        hook_type = self.features.get(top.id, {}).get("hook_type", "") if top else ""
        hook_clause = {
            "冲突反常识型": "高表现内容用冲突开场，第一句就否定一个流行做法",
            "数字清单型": "高表现内容首句就给出可数的结构（N 条/N 步）",
            "疑问悬念型": "高表现内容用问句制造认知缺口，把答案压到正文",
            "结果前置型": "高表现内容首句直接抛结果与量级",
            "故事代入型": "高表现内容用第一人称经历切入，降低说教感",
            "权威背书型": "高表现内容靠可验证的事实/官方动作建立可信度",
            "平铺直叙型": "高表现内容不靠修辞，靠首句直给一个具体事实",
        }.get(hook_type, "高表现内容在第一屏就交付了关键信息")
        return (f"在 {dataset.account} 的受众里，拉开互动量差距的是【{names}】：{hook_clause}，"
                f"而对照组把关键信息埋在了中后段。可直接复用的动作：{actions}。")

    # ------------------------------------------------------------------ 解释力自评
    def _explanatory_power(self, dataset: Dataset, result: AnalysisResult) -> str:
        """评估"文本六维"能否解释真实互动差异，避免过度归因（数据驱动的自我约束）。"""
        high = [a for a in result.post_analyses if a.group == "high"]
        norm = [a for a in result.post_analyses if a.group == "normal"]
        if not high or not norm:
            return "样本不足，无法评估解释力。"
        gap = statistics.mean([a.viral_index for a in high]) - \
            statistics.mean([a.viral_index for a in norm])
        strong_n = sum(1 for v in result.variables if v.confidence == "强因果")
        m_high = statistics.mean([p.metrics.total for p in dataset.high_performers]) or 1
        m_norm = statistics.mean([p.metrics.total for p in dataset.control_group]) or 0
        ratio = m_high / max(m_norm, 1)
        if gap >= 8 and strong_n >= 2:
            return (f"解释力强：高表现组六维综合指数比对照组高 {gap:+.1f} 分，"
                    f"且有 {strong_n} 个强因果变量，写法差异足以解释 {ratio:.0f}x 的互动差距。")
        if gap >= 3 or strong_n >= 1:
            return (f"解释力中等：六维指数仅高 {gap:+.1f} 分（真实互动差距 {ratio:.0f}x），"
                    f"文案写法只能部分解释，选题领域与发布时机同样关键，模板需配合选题清单使用。")
        return (f"解释力弱（重要提示）：两组六维指数几乎无差异（{gap:+.1f} 分），"
                f"但真实互动差距达 {ratio:.0f}x —— 说明该账号的互动差异主要由"
                f"选题本身的关注度、平台推荐与发布时机决定，不应把功劳归给文案技巧。"
                f"下面的模板只用于保证下限，选题仍需单独验证。")

    # ------------------------------------------------------------------ 模板沉淀
    def distill(self, dataset: Dataset, result: AnalysisResult) -> ViralTemplate:
        high_f = [self.features[p.id] for p in dataset.high_performers if p.id in self.features]
        if not high_f:
            high_f = [T.extract_features(p.text, p.published_dt) for p in dataset.posts[:1]]
        hook_type = Counter(f["hook_type"] for f in high_f).most_common(1)[0][0]
        cta_type = Counter(f["cta_type"] for f in high_f).most_common(1)[0][0]
        slot = Counter(f["publish_slot"] for f in high_f).most_common(1)[0][0]
        avg_len = int(statistics.mean([f["char_len"] for f in high_f]))
        avg_para = max(3, round(statistics.mean([f["paragraph_count"] for f in high_f])))
        density = round(statistics.mean([f["info_density"] for f in high_f]), 1)

        # 原样本普遍缺 CTA 时，这本身是可直接吃到的增量空间
        cta_missing = cta_type == "无明确 CTA"
        cta_label = "低门槛互动型（补齐项）" if cta_missing else cta_type
        blocks = [
            {"role": "Hook 钩子", "goal": "前 1 句制造冲突或抛出结论，止住划走动作",
             "rule": f"套用「{hook_type}」句式，控制在 12-30 字，必须含数字或反常识判断"},
            {"role": "冲突/痛点放大", "goal": "让读者确认'这说的就是我'",
             "rule": "1-2 句描述具体场景，不要抽象名词"},
            {"role": "论据/清单", "goal": "交付可带走的干货，撑住信息密度",
             "rule": f"分 2-4 条，每条一个信息点，整篇密度不低于 {density} 点/百字"},
            {"role": "机制解释", "goal": "回答'为什么有效'，建立可信度",
             "rule": "给出原因或原理，1-2 句，可引用真实数据"},
            {"role": "收束金句", "goal": "提供可转述的一句话，提升转发率",
             "rule": "1 句，短，可独立成立"},
            {"role": "CTA + 互动装置", "goal": "把注意力转成评论/收藏",
             "rule": (f"原样本普遍缺 CTA，这是可直接吃到的增量：补一条「低门槛互动型」CTA"
                      if cta_missing else f"套用「{cta_type}」") + "，并附 1 个开放式提问或二选一"},
        ]
        checklist = [
            f"首句是否是「{hook_type}」且 ≤30 字？",
            f"全文是否 {int(avg_len*0.8)}-{int(avg_len*1.2)} 字、约 {avg_para} 段？",
            f"信息密度是否 ≥ {density} 点/百字？",
            "是否有具体数字或可验证事实？",
            f"结尾是否有「{cta_label}」+ 1 个互动装置？",
            f"发布时间是否落在「{slot}」？",
        ]
        return ViralTemplate(
            name=f"{hook_type}·{cta_label} 结构模板",
            applicable_scene=f"{dataset.platform} 平台 / {dataset.account} 同类受众的观点与干货型内容",
            blocks=blocks,
            hook_patterns=self._hook_patterns(hook_type, high_f),
            cta_patterns=self._cta_patterns(cta_type),
            publish_window=slot,
            checklist=checklist,
            length_range=f"{int(avg_len*0.8)}-{int(avg_len*1.2)} 字（高表现组均值 {avg_len} 字）",
        )

    @staticmethod
    def _hook_patterns(hook_type: str, high_f: List[Dict]) -> List[str]:
        base = {
            "冲突反常识型": ["大家都在做 X，但数据显示 X 恰恰是无效的",
                             "不是你不够努力，是 X 这一步从一开始就错了"],
            "数字清单型": ["拆了 N 条爆款后，只有 3 条规律反复出现",
                           "N 个动作里，真正影响结果的只有第 2 个"],
            "疑问悬念型": ["为什么同样的选题，他的数据是你的 10 倍？",
                           "到底是什么决定了一条内容能不能被推荐？"],
            "结果前置型": ["30 天把互动量做了 5 倍，方法只有一条",
                           "从 0 到 X，我只改了开头这一句"],
            "故事代入型": ["上周我把同一个观点写了两遍，数据差了 20 倍",
                           "第一次拆爆款时，我完全找错了变量"],
            "权威背书型": ["官方刚更新了推荐逻辑，这条变化最值得注意",
                           "新数据出来了，和大多数人的直觉相反"],
            "平铺直叙型": ["先给结论：X 才是关键变量", "一句话说清 X 的底层逻辑"],
        }
        patterns = base.get(hook_type, base["平铺直叙型"])
        sample = T.first_line(high_f[0].get("hook_evidence", "")) if high_f else ""
        if sample:
            patterns = patterns + [f"（高表现样本参考句式：{T.truncate(sample, 36)}）"]
        return patterns

    @staticmethod
    def _cta_patterns(cta_type: str) -> List[str]:
        return {
            "低门槛互动型": ["你踩过哪一条？评论区说一个，我逐条回", "A 还是 B，评论区投一票"],
            "收藏转发型": ["先收藏，下次写之前照着自检一遍", "转给那个还在踩坑的同事"],
            "关注沉淀型": ["下期拆解发布时段的影响，关注不迷路"],
            "导流转化型": ["完整清单放在评论区第一条"],
            # 原样本没有 CTA，说明这是空白增量：直接给一条低门槛互动 CTA
            "无明确 CTA": ["你更认同哪一条？评论区说一个，我把反例也补上",
                           "先收藏，下次动笔前照着自检一遍"],
        }.get(cta_type, ["评论区聊聊你的做法"])

    # ------------------------------------------------------------------ LLM 增强
    def _llm_enrich(self, pa: PostAnalysis, post: Post, dataset: Dataset,
                    group: str, features: Dict) -> bool:
        if not self.llm.available:
            return False
        try:
            heur = "\n".join(f"- {d.name}: {d.score} 分 | {d.insight}" for d in pa.dimensions.values())
            data = self.llm.chat_json(SYSTEM_PROMPT, ANALYSIS_PROMPT.format(
                group=group, account=dataset.account, published_at=post.published_at,
                metrics=post.metrics.brief(), text=T.truncate(post.text, 1800),
                heuristics=heur))
            for key, _ in DIMENSIONS:
                item = (data.get("dimensions") or {}).get(key) or {}
                if key in pa.dimensions and item:
                    d = pa.dimensions[key]
                    if isinstance(item.get("score"), (int, float)):
                        d.score = int(max(0, min(100, item["score"])))
                    d.insight = item.get("insight") or d.insight
                    d.evidence = item.get("evidence") or d.evidence
            pa.one_line = data.get("one_line") or pa.one_line
            return True
        except (LLMError, Exception) as exc:
            self.log(f"LLM 拆解增强失败，保留规则引擎结果：{exc}")
            return False

    def _llm_diff(self, dataset: Dataset, result: AnalysisResult) -> bool:
        if not self.llm.available or not result.variables:
            return False
        try:
            def block(posts):
                return "\n\n".join(
                    f"[{p.id}] {p.metrics.brief()} | {p.published_at}\n{T.truncate(p.text, 600)}"
                    for p in posts)

            table = "\n".join(f"- {v.name}: 高={v.high_value} 普通={v.normal_value} 差值={v.delta}"
                              for v in result.variables[:8])
            data = self.llm.chat_json(SYSTEM_PROMPT, DIFF_PROMPT.format(
                high_block=block(dataset.high_performers),
                normal_block=block(dataset.control_group),
                variable_table=table))
            by_name = {v.name: v for v in result.variables}
            for kv in data.get("key_variables") or []:
                v = by_name.get(kv.get("name"))
                if v:
                    v.confidence = kv.get("confidence") or v.confidence
                    v.explanation = kv.get("explanation") or v.explanation
                    v.actionable = kv.get("actionable") or v.actionable
            result.core_insight = data.get("core_insight") or result.core_insight
            result.rejected_hypotheses = data.get("rejected_hypotheses") or []
            # 模板也交给 LLM 精修
            tpl_data = self.llm.chat_json(SYSTEM_PROMPT, TEMPLATE_PROMPT.format(
                core_insight=result.core_insight,
                key_variables=table,
                structure_facts="; ".join(
                    f"{p.id}: " + "→".join(self.features.get(p.id, {}).get("structure_blocks", []))
                    for p in dataset.high_performers)))
            if tpl_data.get("blocks"):
                base = self.distill(dataset, result)
                merged = ViralTemplate.from_dict({**base.to_dict(), **{
                    k: v for k, v in tpl_data.items() if k in ViralTemplate.__dataclass_fields__ and v}})
                result.template = merged
            return True
        except Exception as exc:
            self.log(f"LLM 归因增强失败，保留规则引擎结果：{exc}")
            return False
