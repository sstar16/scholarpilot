"""
Full-text sectioning for probe-based reading.

把学术论文全文切成"探针可独立消化"的小段，策略：
1. 优先按标题分段（markdown `##`、带编号 heading、经典 IMRaD 关键词）
2. 没有明显结构时退化为等宽字符窗口 + 重叠
3. 每段产出 (idx, label, char_start, char_end, text)

section 大小控制：单段不超过 MAX_SECTION_CHARS；超过则内部再按字符窗口切。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import List, Tuple


MAX_SECTION_CHARS = 6000          # 单段上限（便于探针一次消化）
MIN_SECTION_CHARS = 400           # 小于此认为不值得独立切，合并到上一段
WINDOW_CHARS = 5000               # 退化策略的窗口大小
WINDOW_OVERLAP = 500              # 相邻窗口重叠，避免边界截断


# 常见学术论文 heading 的识别正则：
# - markdown 风格 `##`、`###` 开头
# - 纯大写章节名 `ABSTRACT`
# - 经典 IMRaD 词 + 编号或冒号："1. Introduction"、"2 Methods"、"Results:"
# - 也容忍中文段头 "方法"、"结果"
_HEADING_PATTERNS: List[re.Pattern] = [
    re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE),
    re.compile(
        r"^(?:\d+(?:\.\d+)*\.?\s+)?"
        r"(Abstract|Introduction|Background|Related\s+Work|Preliminaries|"
        r"Methods?|Methodology|Approach|Experiments?|"
        r"Results?|Evaluation|Discussion|Analysis|"
        r"Ablation(?:\s+Stud(?:y|ies))?|Conclusions?|"
        r"Limitations?|Future\s+Work|Acknowledge?ments?|References?|Appendix|"
        r"摘要|引言|方法|实验|结果|讨论|结论|参考文献)"
        r"\s*[:：]?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]


@dataclass
class Section:
    idx: int
    label: str
    char_start: int
    char_end: int
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _find_heading_anchors(text: str) -> List[Tuple[int, str]]:
    """扫出所有可识别的 heading 位置 [(char_pos, label), ...]，按位置升序。"""
    anchors: List[Tuple[int, str]] = []
    for pat in _HEADING_PATTERNS:
        for m in pat.finditer(text):
            pos = m.start()
            label = m.group(m.lastindex).strip() if m.lastindex else m.group(0).strip()
            label = re.sub(r"\s+", " ", label)[:80]
            anchors.append((pos, label))
    # 去重 + 排序
    anchors.sort(key=lambda x: x[0])
    dedup: List[Tuple[int, str]] = []
    for pos, label in anchors:
        if dedup and pos - dedup[-1][0] < 20:
            continue
        dedup.append((pos, label))
    return dedup


def _window_split(text: str, base_idx: int, label_prefix: str, base_offset: int = 0) -> List[Section]:
    """等宽窗口 + 重叠兜底切法。label_prefix 用于给没有 heading 的文档起个可读标签。"""
    out: List[Section] = []
    n = len(text)
    if n == 0:
        return out
    start = 0
    step = max(WINDOW_CHARS - WINDOW_OVERLAP, 1)
    idx = base_idx
    while start < n:
        end = min(start + WINDOW_CHARS, n)
        chunk = text[start:end]
        out.append(Section(
            idx=idx,
            label=f"{label_prefix} #{idx + 1}",
            char_start=base_offset + start,
            char_end=base_offset + end,
            text=chunk,
        ))
        idx += 1
        if end >= n:
            break
        start += step
    return out


def split_into_sections(text: str) -> List[Section]:
    """
    主入口：把 full_text 切成 Section 列表。

    - 若检测到 ≥3 个 heading 锚点 → 按 heading 切
    - 否则 → 按 WINDOW_CHARS 等宽 + 重叠
    - heading 切法中，单段超过 MAX_SECTION_CHARS 会再做一次内部窗口切
    """
    if not text or not text.strip():
        return []

    anchors = _find_heading_anchors(text)
    if len(anchors) < 3:
        # 结构不明显 → 窗口法
        return _window_split(text, base_idx=0, label_prefix="片段")

    # 把开头到第一个 heading 之间视为"Preamble"
    sections: List[Section] = []
    idx = 0

    first_pos = anchors[0][0]
    if first_pos > MIN_SECTION_CHARS:
        pre = text[:first_pos]
        if len(pre) > MAX_SECTION_CHARS:
            sections.extend(_window_split(pre, base_idx=idx, label_prefix="开篇", base_offset=0))
            idx = len(sections)
        else:
            sections.append(Section(
                idx=idx,
                label="开篇",
                char_start=0,
                char_end=first_pos,
                text=pre,
            ))
            idx += 1

    # 相邻 heading 之间一段
    boundaries = [a[0] for a in anchors] + [len(text)]
    labels = [a[1] for a in anchors]
    for i, label in enumerate(labels):
        start = boundaries[i]
        end = boundaries[i + 1]
        chunk = text[start:end]
        if len(chunk) < MIN_SECTION_CHARS and sections:
            # 太短合并到上一段
            last = sections[-1]
            sections[-1] = Section(
                idx=last.idx,
                label=f"{last.label} + {label}",
                char_start=last.char_start,
                char_end=end,
                text=last.text + chunk,
            )
            continue
        if len(chunk) > MAX_SECTION_CHARS:
            sub = _window_split(chunk, base_idx=idx, label_prefix=label, base_offset=start)
            sections.extend(sub)
            idx = len(sections)
        else:
            sections.append(Section(
                idx=idx,
                label=label,
                char_start=start,
                char_end=end,
                text=chunk,
            ))
            idx += 1

    # 重新排 idx，确保连续
    for i, s in enumerate(sections):
        sections[i] = Section(
            idx=i,
            label=s.label,
            char_start=s.char_start,
            char_end=s.char_end,
            text=s.text,
        )
    return sections


def split_preview(text: str, max_sections: int = 20) -> List[dict]:
    """调试/日志用：切完返回精简 dict，省内存。"""
    secs = split_into_sections(text)[:max_sections]
    return [
        {
            "idx": s.idx,
            "label": s.label,
            "char_start": s.char_start,
            "char_end": s.char_end,
            "len": len(s.text),
            "preview": s.text[:120].replace("\n", " "),
        }
        for s in secs
    ]
