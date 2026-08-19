"""文本特征工具测试：Hook 分类、CTA 识别、CJK 宽度、信息密度等。

这些是"可解释归因"的基础，必须可复算、行为确定。
"""

from src.utils import text as T


def test_classify_hook_contrarian():
    name, _, _ = T.classify_hook("别再这样做了，大部分人都理解错了")
    assert name == "冲突反常识型"


def test_classify_hook_listicle():
    name, _, _ = T.classify_hook("3 个方法让你的互动量翻倍")
    assert name == "数字清单型"


def test_classify_hook_question():
    name, _, _ = T.classify_hook("为什么同样的选题，他的数据是你的 10 倍？")
    assert name == "疑问悬念型"


def test_classify_hook_plain_fallback():
    name, _, _ = T.classify_hook("just a plain statement without any hook")
    assert name == "平铺直叙型"


def test_detect_cta_low_friction():
    name, _, _ = T.detect_cta("说真的，评论区聊聊你的看法")
    assert name == "低门槛互动型"


def test_detect_cta_missing():
    name, base, _ = T.detect_cta("no call to action in this paragraph at all")
    assert name == "无明确 CTA"
    assert base == 25


def test_display_width_cjk():
    assert T.display_width("ab") == 2
    assert T.display_width("中文") == 4
    assert T.display_width("a中") == 3


def test_truncate_keeps_width():
    out = T.truncate("这是一段很长很长很长很长的中文文本", 8)
    assert T.display_width(out) <= 8
    assert out.endswith("…")


def test_info_density_positive():
    d = T.info_density("三个要点：第一是 A；第二是 B；第三是 C。")
    assert d > 0


def test_extract_features_keys():
    f = T.extract_features("别再错了！3 个方法。评论区聊聊你的看法", None)
    assert f["hook_type"] == "冲突反常识型"
    assert f["has_number"] is True
    assert f["cta_type"] == "低门槛互动型"
