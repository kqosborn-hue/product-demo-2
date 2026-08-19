"""文本特征提取工具集（纯标准库）。

这里的每个函数都是"可解释归因"的基础：分析结论必须能落到
某个具体的、可复算的文本特征上，而不是模型的一句主观判断。
中英文双语兼容（Hook/CTA 句式同时匹配中英模式）。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 宽度 / 截断
_WIDE = ("F", "W")


def display_width(s: str) -> int:
    """终端显示宽度（CJK 全角字符按 2 计）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in _WIDE else 1 for ch in str(s))


def truncate(s: str, width: int, ellipsis: str = "…") -> str:
    s = str(s).replace("\n", " ⏎ ")
    if display_width(s) <= width:
        return s
    out, w, limit = [], 0, max(1, width - display_width(ellipsis))
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in _WIDE else 1
        if w + cw > limit:
            break
        out.append(ch)
        w += cw
    return "".join(out) + ellipsis


def pad(s: str, width: int, align: str = "left") -> str:
    gap = max(0, width - display_width(s))
    if align == "right":
        return " " * gap + s
    if align == "center":
        left = gap // 2
        return " " * left + s + " " * (gap - left)
    return s + " " * gap


# ---------------------------------------------------------------- 基础切分
def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]


_SENT_END = re.compile(r"[。！？!?；;\.]+(?=\s|$)|\n+")


def sentences(text: str) -> List[str]:
    parts = [p.strip() for p in _SENT_END.split(text or "") if p and p.strip()]
    return parts


def char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


# ---------------------------------------------------------------- 特征正则
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|％|倍|万|亿|k|K|w|W)?")
HASHTAG_RE = re.compile(r"#([^#\s]{1,30})#|#(\w{1,30})")
MENTION_RE = re.compile(r"@[\w\u4e00-\u9fa5\-_]{1,30}")
URL_RE = re.compile(r"https?://\S+")
EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001F9FF" "\U0001F600-\U0001F64F" "\U00002600-\U000027BF" "\U0001FA70-\U0001FAFF" "]"
)
BULLET_RE = re.compile(r"(?m)^\s*(?:[-*•·]|\d+[\.、\)]|[一二三四五六七八九十]+[、.])\s*")

HOOK_PATTERNS: List[Tuple[str, int, re.Pattern]] = [
    ("冲突反常识型", 92, re.compile(
        r"(其实|恰恰相反|误区|大错特错|别再|千万不要|不是.*而是|真相|被高估|被低估|翻车|踩坑|"
        r"stop|myth|wrong|actually|nobody tells|don'?t|worst|surprising)", re.I)),
    ("数字清单型", 84, re.compile(
        r"^\s*\W*(\d+\s*(个|条|招|步|种|点|个理由|things|ways|steps|lessons|rules|tips))", re.I)),
    ("疑问悬念型", 86, re.compile(r"(为什么|凭什么|怎么做到|到底|吗[？?]|如何|what if|why|how i|how to)", re.I)),
    ("结果前置型", 82, re.compile(
        r"(\d+\s*(天|周|月|年|小时).{0,12}(涨|做到|突破|从0|赚|增长))|(\bfrom\b.*\bto\b)|(增长了|翻了.*倍|"
        r"we (grew|cut|shipped)|\$\d)", re.I)),
    ("故事代入型", 76, re.compile(r"(我|我们|昨天|上周|那天|三年前|第一次|离职|复盘|亲测|i (just|finally|spent|built))", re.I)),
    ("权威背书型", 74, re.compile(
        r"(官方|发布|上线|开源|论文|财报|宣布|收购|起诉|裁员|launch|releases?|announce|open.?source|"
        r"acquir|buys?\b|shuts? down|sues?\b|bans?\b|study finds|researchers)", re.I)),
]

CTA_PATTERNS: List[Tuple[str, int, re.Pattern]] = [
    ("低门槛互动型", 88, re.compile(r"(评论区|留言|说说|聊聊|你怎么看|投票|选[一1]|打在评论|tell me|what do you think|thoughts\?)", re.I)),
    ("收藏转发型", 82, re.compile(r"(收藏|转发|分享给|码住|存下来|一键三连|retweet|share this|bookmark)", re.I)),
    ("关注沉淀型", 74, re.compile(r"(关注我|点个关注|持续更新|下期|follow (me|for)|subscribe)", re.I)),
    ("导流转化型", 70, re.compile(r"(点击|链接|私信|领取|评论区领|报名|试用|下载|read more|link in|sign ?up|try it)", re.I)),
]

INTERACTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("开放式提问", re.compile(r"(你(们)?(觉得|认为|会|有没有|怎么)|怎么看|吗[？?]|\?\s*$|what|how|which)", re.I | re.M)),
    ("二选一/站队", re.compile(r"(选[AB1一]|还是|A 还是 B|站队|pick one|or\b.*\?)", re.I)),
    ("投票/打分", re.compile(r"(投票|打分|poll|vote|rate)", re.I)),
    ("悬念留白", re.compile(r"(下期|未完|明天|后续|留个悬念|to be continued|part\s*\d)", re.I)),
    ("话题标签", HASHTAG_RE),
    ("@互动", MENTION_RE),
    ("福利钩子", re.compile(r"(抽奖|免费|领取|送|福利|giveaway|free)", re.I)),
]

TOPIC_SIGNALS: List[Tuple[str, int, re.Pattern]] = [
    ("痛点/焦虑", 22, re.compile(r"(踩坑|翻车|亏|失败|焦虑|内卷|裁员|避坑|难|痛点|bug|fail|risk|threat|vulnerab|breach|lawsuit)", re.I)),
    ("利益/收益", 20, re.compile(r"(涨|赚|变现|收益|降本|提效|免费|省|增长|revenue|profit|save|faster|cheaper|free)", re.I)),
    ("争议/立场", 20, re.compile(r"(争议|吵|反对|批评|抵制|封杀|该不该|之争|vs|sues?|bans?|controvers|criticiz)", re.I)),
    ("新知/认知差", 18, re.compile(r"(原来|竟然|冷知识|底层逻辑|原理|拆解|揭秘|first|new|discovered|turns out|inside)", re.I)),
    ("热点/时效", 18, re.compile(r"(刚刚|今日|最新|突发|官宣|发布|上线|releases?|launch|announce|now|today|2026)", re.I)),
    ("人群指向", 12, re.compile(r"(打工人|新手|小白|运营|程序员|创业者|宝妈|学生|developers?|founders?|beginners?)", re.I)),
]


# ---------------------------------------------------------------- 特征函数
def hashtags(text: str) -> List[str]:
    return ["".join(filter(None, m)) for m in HASHTAG_RE.findall(text or "")]


def mentions(text: str) -> List[str]:
    return MENTION_RE.findall(text or "")


def numbers(text: str) -> List[str]:
    return [n.strip() for n in NUM_RE.findall(text or "")] if text else []


def has_number(text: str) -> bool:
    return bool(re.search(r"\d", text or ""))


def emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text or ""))


def urls(text: str) -> List[str]:
    return URL_RE.findall(text or "")


def classify_hook(text: str) -> Tuple[str, int, str]:
    """返回 (Hook 类型, 基准分, 证据片段)。"""
    head = first_line(text)
    probe = head if len(head) >= 8 else (text or "")[:120]
    for name, base, pattern in HOOK_PATTERNS:
        m = pattern.search(probe)
        if m:
            return name, base, m.group(0)[:40]
    return "平铺直叙型", 45, truncate(probe, 40)


def detect_cta(text: str) -> Tuple[str, int, str]:
    tail = "\n".join((text or "").splitlines()[-3:]) or (text or "")[-160:]
    best = ("无明确 CTA", 25, "缺失")
    for name, base, pattern in CTA_PATTERNS:
        m = pattern.search(text or "")
        if m:
            bonus = 8 if pattern.search(tail) else 0     # CTA 放在结尾更有效
            if base + bonus > best[1]:
                best = (name, base + bonus, m.group(0)[:36])
    return best


def detect_interaction(text: str) -> List[str]:
    found = []
    for name, pattern in INTERACTION_PATTERNS:
        if pattern.search(text or ""):
            found.append(name)
    return found


def count_info_points(text: str) -> int:
    """信息点估算：数字 + 列表项 + 冒号定义 + 转折连接词。"""
    t = text or ""
    pts = len(set(numbers(t)))
    pts += len(BULLET_RE.findall(t))
    pts += len(re.findall(r"[：:]", t))
    pts += len(re.findall(r"(但是|然而|因此|所以|反而|关键是|however|because|therefore)", t, re.I))
    return pts


def info_density(text: str) -> float:
    """每 100 字的有效信息点数量。"""
    n = char_count(text)
    if n == 0:
        return 0.0
    return round(count_info_points(text) / n * 100, 2)


def structure_blocks(text: str) -> List[str]:
    """粗粒度识别段落职能，用于沉淀结构模板。"""
    paras = paragraphs(text)
    labels = []
    for i, p in enumerate(paras):
        if i == 0:
            labels.append("Hook")
        elif BULLET_RE.search(p) or has_number(p):
            labels.append("论据/清单")
        elif re.search(r"(所以|因此|总结|一句话|结论|takeaway)", p, re.I):
            labels.append("收束金句")
        elif any(pat.search(p) for _, _, pat in CTA_PATTERNS):
            labels.append("CTA")
        else:
            labels.append("展开论述")
    return labels or ["Hook"]


SLOTS = [(0, 6, "深夜 00-06"), (6, 11, "早间 06-11"), (11, 14, "午间 11-14"),
         (14, 18, "下午 14-18"), (18, 24, "晚间 18-24")]


def publish_slot(dt: Optional[datetime]) -> str:
    if not dt:
        return "未知时段"
    h = dt.hour
    for start, end, name in SLOTS:
        if start <= h < end:
            return name
    return "未知时段"


def weekday_cn(dt: Optional[datetime]) -> str:
    if not dt:
        return "未知"
    return "周" + "一二三四五六日"[dt.weekday()]


def extract_features(text: str, dt: Optional[datetime] = None) -> Dict[str, object]:
    """一次性抽取全部可比对特征（分析与归因共用同一份事实）。"""
    hook_type, hook_base, hook_evidence = classify_hook(text)
    cta_type, cta_base, cta_evidence = detect_cta(text)
    devices = detect_interaction(text)
    paras = paragraphs(text)
    sents = sentences(text)
    return {
        "hook_type": hook_type,
        "hook_base": hook_base,
        "hook_evidence": hook_evidence,
        "hook_len": len(first_line(text)),
        "cta_type": cta_type,
        "cta_base": cta_base,
        "cta_evidence": cta_evidence,
        "interaction_devices": devices,
        "interaction_count": len(devices),
        "char_len": char_count(text),
        "paragraph_count": len(paras),
        "avg_sentence_len": round(sum(len(s) for s in sents) / len(sents), 1) if sents else 0,
        "info_points": count_info_points(text),
        "info_density": info_density(text),
        "has_number": has_number(text),
        "number_count": len(set(numbers(text))),
        "hashtag_count": len(hashtags(text)),
        "mention_count": len(mentions(text)),
        "emoji_count": emoji_count(text),
        "has_url": bool(urls(text)),
        "structure_blocks": structure_blocks(text),
        "publish_slot": publish_slot(dt),
        "weekday": weekday_cn(dt),
    }
