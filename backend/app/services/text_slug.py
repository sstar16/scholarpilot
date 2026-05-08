"""
Shared slugify utility for URL-friendly file names.

Produces hyphen-separated lowercase slugs for English;
preserves CJK characters as-is (they serve as visual slug).

Example:
    "Attention Is All You Need" → "attention-is-all-you-need"
    "一种固态锂电池电解质组合物" → "一种固态锂电池电解质组合物"
    "" → "untitled"
"""
from __future__ import annotations

import re
from typing import Optional

_FS_UNSAFE = re.compile(r'[<>:"/\\|?*\u00a0]')
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WS = re.compile(r"\s+")
_COLLAPSE_HYPHEN = re.compile(r"-+")
_CJK_RANGE = re.compile(r"[\u4e00-\u9fff]")


def slugify(text: Optional[str], max_len: int = 60) -> str:
    """
    Convert a title to a file-system / URL safe slug.

    For ASCII input: lowercases, replaces whitespace with hyphens, strips unsafe chars.
    For CJK input: preserves characters as-is (lowercase has no effect on CJK).
    Mixed input: CJK preserved, ASCII lowercased and hyphenated.
    """
    if not text:
        return "untitled"
    cleaned = _CONTROL.sub("", text)
    cleaned = _FS_UNSAFE.sub(" ", cleaned)
    cleaned = _WS.sub("-", cleaned.strip())
    # Split CJK from ASCII preservation: lowercase only ASCII
    parts = []
    for ch in cleaned:
        if _CJK_RANGE.match(ch):
            parts.append(ch)
        else:
            parts.append(ch.lower())
    cleaned = "".join(parts)
    cleaned = _COLLAPSE_HYPHEN.sub("-", cleaned)
    cleaned = cleaned.strip("-_. ")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("-_. ")
    return cleaned or "untitled"
