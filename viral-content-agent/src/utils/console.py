"""终端呈现层：负责把"思考过程 / 对比表格 / 人工确认闸门"渲染得一目了然。

Demo 效果要求：
- 思考过程逐条打印，带步骤编号与灰色缩进；
- 对比表格 CJK 对齐、支持高亮列；
- 人工确认环节用醒目的黄底红字警示框 + 分隔线，明确"等待用户输入"。
"""

from __future__ import annotations

import os
import sys
import shutil
import time
from typing import Iterable, List, Optional, Sequence

from .text import display_width, pad, truncate

# ---------------------------------------------------------------- 颜色支持
_STYLES = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "italic": "\033[3m",
    "underline": "\033[4m", "blink": "\033[5m", "reverse": "\033[7m",
    "black": "\033[30m", "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m", "white": "\033[37m",
    "gray": "\033[90m", "bright_red": "\033[91m", "bright_green": "\033[92m",
    "bright_yellow": "\033[93m", "bright_blue": "\033[94m", "bright_magenta": "\033[95m",
    "bright_cyan": "\033[96m",
    "on_red": "\033[41m", "on_green": "\033[42m", "on_yellow": "\033[43m",
    "on_blue": "\033[44m", "on_magenta": "\033[45m", "on_cyan": "\033[46m",
    "on_gray": "\033[100m",
}


def _init_windows_vt() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        return True
    except Exception:
        return False


def _detect_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not sys.stdout.isatty():
        return False
    return _init_windows_vt()


_COLOR_ENABLED = _detect_color()

# Windows 控制台中文输出兜底
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def set_color(enabled: bool) -> None:
    global _COLOR_ENABLED
    _COLOR_ENABLED = enabled and _detect_color()


def c(text: str, *styles: str) -> str:
    if not _COLOR_ENABLED or not styles:
        return str(text)
    prefix = "".join(_STYLES.get(s, "") for s in styles)
    return f"{prefix}{text}{_STYLES['reset']}"


def term_width(default: int = 100) -> int:
    try:
        return max(72, min(shutil.get_terminal_size((default, 24)).columns, 120))
    except Exception:
        return default


# ---------------------------------------------------------------- 基础组件
def blank() -> None:
    print()


def rule(title: str = "", char: str = "─", style: str = "gray") -> None:
    w = term_width()
    if not title:
        print(c(char * w, style))
        return
    label = f" {title} "
    side = max(0, (w - display_width(label)) // 2)
    line = char * side + label + char * max(0, w - side - display_width(label))
    print(c(line, style))


def banner(title: str, subtitle: str = "") -> None:
    w = term_width()
    print(c("╔" + "═" * (w - 2) + "╗", "cyan"))
    print(c("║", "cyan") + c(pad(f"  {title}", w - 2), "bold", "bright_cyan") + c("║", "cyan"))
    if subtitle:
        print(c("║", "cyan") + c(pad(f"  {subtitle}", w - 2), "gray") + c("║", "cyan"))
    print(c("╚" + "═" * (w - 2) + "╝", "cyan"))


def step(index: int, total: int, title: str) -> None:
    blank()
    tag = f" 第{index}步 / {total} "
    print(c(tag, "bold", "on_blue", "white") + " " + c(title, "bold", "bright_cyan"))
    print(c("─" * term_width(), "blue"))


def think(lines: Iterable[str], header: str = "思考过程") -> None:
    """打印 Agent 的推理链，Demo 时让评审看得见"它在想什么"。"""
    print(c(f"  ╭─ 🧠 {header}", "magenta"))
    for line in lines:
        print(c("  │ ", "magenta") + c("· ", "gray") + c(str(line), "white"))
        time.sleep(0.02)
    print(c("  ╰" + "─" * 28, "magenta"))


def action(text: str) -> None:
    print(c("  ⚙ ", "bright_blue") + c(text, "bright_blue"))


def info(text: str) -> None:
    print(c("  ℹ ", "cyan") + str(text))


def ok(text: str) -> None:
    print(c("  ✔ ", "bright_green") + c(str(text), "green"))


def warn(text: str) -> None:
    print(c("  ⚠ ", "bright_yellow") + c(str(text), "yellow"))


def err(text: str) -> None:
    print(c("  ✘ ", "bright_red") + c(str(text), "red"))


def kv(key: str, value: str, key_width: int = 14) -> None:
    print("  " + c(pad(key, key_width), "gray") + str(value))


def bullet(text: str, indent: int = 2, marker: str = "•") -> None:
    print(" " * indent + c(f"{marker} ", "cyan") + str(text))


def quote(text: str, indent: int = 4) -> None:
    for line in str(text).splitlines() or [""]:
        print(" " * indent + c("▎", "gray") + " " + c(line, "white"))


# ---------------------------------------------------------------- 表格
def table(headers: Sequence[str], rows: Sequence[Sequence[object]],
          aligns: Optional[Sequence[str]] = None, title: str = "",
          highlight_rows: Optional[Sequence[int]] = None,
          max_col: int = 34) -> None:
    """CJK 对齐的对比表格。highlight_rows 用于突出"高表现内容"行。"""
    if title:
        blank()
        print("  " + c(title, "bold", "bright_yellow"))
    data = [[str(x) if x is not None else "-" for x in row] for row in rows]
    cols = len(headers)
    aligns = list(aligns or ["left"] * cols)
    widths = []
    for i in range(cols):
        cells = [str(headers[i])] + [r[i] for r in data]
        widths.append(min(max(display_width(x) for x in cells), max_col))
    data = [[truncate(r[i], widths[i]) for i in range(cols)] for r in data]
    head = [truncate(str(headers[i]), widths[i]) for i in range(cols)]

    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    sep = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    print("  " + c(top, "gray"))
    print("  " + c("│", "gray") + c("│", "gray").join(
        " " + c(pad(head[i], widths[i], "center"), "bold", "cyan") + " " for i in range(cols)) + c("│", "gray"))
    print("  " + c(sep, "gray"))
    hl = set(highlight_rows or [])
    for ri, row in enumerate(data):
        cells = []
        for i in range(cols):
            txt = pad(row[i], widths[i], aligns[i])
            cells.append(" " + (c(txt, "bright_yellow", "bold") if ri in hl else txt) + " ")
        print("  " + c("│", "gray") + c("│", "gray").join(cells) + c("│", "gray"))
    print("  " + c(bot, "gray"))


def bar(value: float, maximum: float, width: int = 18, style: str = "bright_green") -> str:
    if maximum <= 0:
        return ""
    filled = int(round(min(1.0, value / maximum) * width))
    return c("█" * filled, style) + c("░" * (width - filled), "gray")


# ---------------------------------------------------------------- 人工确认闸门
def human_gate(prompt: str, hint: str = "确认 / 修改 / 取消") -> None:
    """醒目的"等待人工输入"提示块。"""
    w = term_width()
    blank()
    print(c("▛" + "▀" * (w - 2) + "▜", "bright_yellow"))
    label = "  ⏸  HUMAN-IN-THE-LOOP · 工作流已强制暂停  ⏸"
    print(c("▌", "bright_yellow") + c(pad(label, w - 2), "bold", "on_yellow", "black") + c("▐", "bright_yellow"))
    print(c("▌", "bright_yellow") + pad("", w - 2) + c("▐", "bright_yellow"))
    for line in _wrap(prompt, w - 8):
        print(c("▌", "bright_yellow") + c(pad("   " + line, w - 2), "bright_white", "bold") + c("▐", "bright_yellow"))
    print(c("▌", "bright_yellow") + c(pad("   可选操作：" + hint, w - 2), "gray") + c("▐", "bright_yellow"))
    print(c("▙" + "▄" * (w - 2) + "▟", "bright_yellow"))


def ask(prompt: str = "请输入指令") -> str:
    marker = c(" ▶ ", "on_red", "white", "bold") + c(f" {prompt} ", "bold", "bright_red") + c("» ", "bright_yellow")
    try:
        return input(marker).strip()
    except (EOFError, KeyboardInterrupt):
        blank()
        return ""


def _wrap(text: str, width: int) -> List[str]:
    out: List[str] = []
    for raw in str(text).splitlines() or [""]:
        line, w = "", 0
        for ch in raw:
            cw = display_width(ch)
            if w + cw > width:
                out.append(line)
                line, w = ch, cw
            else:
                line += ch
                w += cw
        out.append(line)
    return out


def wrapped(text: str, indent: int = 4, width: Optional[int] = None) -> None:
    width = width or (term_width() - indent - 2)
    for line in _wrap(text, width):
        print(" " * indent + line)
