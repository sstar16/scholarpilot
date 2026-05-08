"""
Markdown prompt loader — 把 agent/skill/数据源规则从 Python 常量搬到 md 文件。

设计参考 Claude Code 的 skill/agent md 加载机制：
- YAML frontmatter + 正文 body
- mtime 热重载（改了 md 下次 load 自动生效）
- Parser 永不抛异常，解析失败 warn log + 返回空 meta
- 变量替换用 string.Template（$var / ${var}），不碰 body 里的 {} 字面量

用法:

    from app.services.prompt_loader import load_prompt

    pf = load_prompt("agents/query_plan_agentic")
    system_prompt = pf.body
    max_iter = pf.get("max_iterations", 5)

    # 有变量时
    rendered = pf.render(source="openalex", year=2026)

启动时做一次批量校验（可选）:

    from app.services.prompt_loader import load_all
    load_all()  # 任何解析错在这里暴露
"""
from __future__ import annotations

import logging
import re
import string
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

_cache: dict[str, "PromptFile"] = {}


class PromptFile:
    """一个加载好的 md prompt 文件。"""

    __slots__ = ("name", "path", "meta", "body", "mtime")

    def __init__(
        self,
        name: str,
        path: Path,
        meta: dict,
        body: str,
        mtime: float,
    ) -> None:
        self.name = name
        self.path = path
        self.meta = meta
        self.body = body
        self.mtime = mtime

    def get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)

    def render(self, **vars: Any) -> str:
        """
        用 string.Template 做变量替换（$var / ${var}）。
        选 Template 是为了不碰 body 里 JSON 字面量的花括号。
        """
        if not vars:
            return self.body
        try:
            return string.Template(self.body).safe_substitute(**vars)
        except (KeyError, ValueError) as e:
            logger.warning("[prompt_loader] render %s failed: %s", self.name, e)
            return self.body

    def __repr__(self) -> str:
        return (
            f"PromptFile(name={self.name!r}, "
            f"version={self.meta.get('version', '?')}, "
            f"body_len={len(self.body)})"
        )


def _parse_frontmatter(text: str, source: str = "") -> tuple[dict, str]:
    """
    解析 `---\\nYAML\\n---\\n<body>`。
    Claude Code 的经验：parser 永不抛异常，坏 md 只打日志返回空 meta。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    yaml_text = m.group(1) or ""
    body = text[m.end():]

    try:
        parsed = yaml.safe_load(yaml_text)
    except Exception as e:
        logger.warning(
            "[prompt_loader] YAML parse failed in %s: %s", source, e,
        )
        return {}, body

    if parsed is None:
        return {}, body
    if not isinstance(parsed, dict):
        logger.warning(
            "[prompt_loader] frontmatter in %s is not a mapping, got %s",
            source, type(parsed).__name__,
        )
        return {}, body

    return parsed, body


def load_prompt(name: str, *, force_reload: bool = False) -> PromptFile:
    """
    加载一个 md prompt，mtime 热重载。

    Args:
        name: 相对路径，不带 .md。例："agents/query_plan_agentic"
        force_reload: 跳过 mtime 缓存，强制重读

    Raises:
        FileNotFoundError: md 文件不存在（这是该爆的错，启动时就暴露）
    """
    path = (PROMPTS_ROOT / f"{name}.md").resolve()
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {path}")

    mtime = path.stat().st_mtime
    cached = _cache.get(name)
    if cached is not None and cached.mtime == mtime and not force_reload:
        return cached

    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text, source=name)

    pf = PromptFile(
        name=name,
        path=path,
        meta=meta,
        body=body.strip(),
        mtime=mtime,
    )
    _cache[name] = pf

    if cached is None:
        logger.info(
            "[prompt_loader] loaded %s (version=%s)",
            name, meta.get("version", "?"),
        )
    else:
        logger.info("[prompt_loader] reloaded %s (mtime changed)", name)

    return pf


def load_all(pattern: str = "**/*.md") -> dict[str, PromptFile]:
    """
    加载 prompts/ 下所有 md。用于启动时校验或 DevTools 展示。
    返回 {name: PromptFile}，name 为不带扩展名的相对路径。
    """
    result: dict[str, PromptFile] = {}
    if not PROMPTS_ROOT.is_dir():
        logger.warning("[prompt_loader] prompts root missing: %s", PROMPTS_ROOT)
        return result

    for path in PROMPTS_ROOT.glob(pattern):
        if not path.is_file():
            continue
        name = path.relative_to(PROMPTS_ROOT).with_suffix("").as_posix()
        try:
            result[name] = load_prompt(name)
        except Exception as e:
            logger.error("[prompt_loader] failed to load %s: %s", name, e)
    return result


def clear_cache() -> None:
    """测试用。生产环境靠 mtime 自动失效。"""
    _cache.clear()
