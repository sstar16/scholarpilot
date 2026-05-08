"""SKILL.md Loader: 扫目录, 解析 frontmatter, 注册到 SkillRegistry.

这是用户/管理员定义"研究风格 / Persona"的入口。每个 .md 文件 = 一个 skill,
带 yaml frontmatter 描述触发条件 + hook 注入点, body 是要拼到 system prompt 的人话。

工作流程:
1. startup 时 register_markdown_skills() 被 lifespan 调用
2. 扫 DEFAULT_SKILL_DIRS（内置 < 用户全局 < 项目级，后注册覆盖前者）
3. 每个 .md → MarkdownSkill → SkillDefinition + MarkdownSkillExecutor
4. 注册到 SkillRegistry.get_instance()
5. 在 LLM 调用前由 skill_injector.maybe_inject_skill 决定是否激活
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认 skill 目录, 顺序很重要: 后注册的同名 skill 覆盖前注册的
# 1. 项目内置示例（ship 到 git, 给所有用户做 baseline）
# 2. 用户全局自定义（~/.scholarpilot/skills, 用户私有）
# 3. 项目级覆盖（cwd/.scholarpilot/skills, 当前部署专属）
DEFAULT_SKILL_DIRS = [
    Path(__file__).parent.parent.parent.parent.parent / "skills_builtin",  # backend/app/harness/skills/markdown_loader.py → repo root
    Path.home() / ".scholarpilot" / "skills",
    Path.cwd() / ".scholarpilot" / "skills",
]

# kebab-case: 字母数字 + 连字符, 必须以字母/数字开头结尾
_KEBAB_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
# frontmatter 起止
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass
class MarkdownSkill:
    """从 .md 解析出的 skill 定义 (运行时数据载体, 与 SkillDefinition 不同)."""
    name: str                          # 唯一 ID, kebab-case
    description: str                   # 一句话描述
    body: str                          # markdown body (frontmatter 之后的全文, 拼进 prompt)
    source_path: str                   # 原始 .md 路径 (debug)
    triggers: list[str] = field(default_factory=list)         # 命中关键词
    hook_points: list[str] = field(default_factory=list)      # ['collab_respond', 'summary', ...]
    priority: int = 0                  # 同时命中时按 desc 排序
    persona_role: str = "system_prefix"  # 'system_prefix' | 'system_suffix'


# ────────────── frontmatter parser ──────────────

def _try_yaml_load(text: str) -> Optional[dict]:
    """尝试用 PyYAML; 不可用返回 None 让手写 parser 接管."""
    try:
        import yaml  # type: ignore
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
            return None
        except Exception as e:
            logger.warning("[markdown_loader] yaml parse failed, falling back: %s", e)
            return None
    except ImportError:
        return None


def _strip_inline_comment(line: str) -> str:
    """裁掉 ' # comment' (yaml 风格), 但保留引号内的 #."""
    in_quote = None
    for i, ch in enumerate(line):
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in "'\"":
            in_quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line


def _parse_scalar(raw: str) -> Any:
    """简单标量: 数字 / true/false / null / 'string' / "string" / 裸字符串."""
    s = raw.strip()
    if not s:
        return ""
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    # 数字
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        pass
    # quoted string
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_inline_list(raw: str) -> list:
    """[a, b, c] / ['a', 'b'] / [1, 2, 3] → list."""
    s = raw.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return [_parse_scalar(s)]
    inner = s[1:-1].strip()
    if not inner:
        return []
    items: list = []
    buf = ""
    in_quote: Optional[str] = None
    for ch in inner:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            buf += ch
        elif ch in "'\"":
            in_quote = ch
            buf += ch
        elif ch == ",":
            items.append(_parse_scalar(buf))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(_parse_scalar(buf))
    return items


def _hand_parse_frontmatter(text: str) -> dict:
    """极简 yaml 替代品: 支持 'key: value' 和 'key: [a, b, c]', 无嵌套.

    够用即止 — SKILL.md frontmatter 只有 5-6 个字段, 没必要塞 PyYAML 全套。
    """
    out: dict = {}
    cur_list_key: Optional[str] = None  # 多行 list (- item) 模式
    for raw_line in text.splitlines():
        line = _strip_inline_comment(raw_line.rstrip())
        if not line.strip():
            cur_list_key = None
            continue

        # 多行 list: '  - item'
        stripped = line.lstrip()
        if cur_list_key and stripped.startswith("- "):
            out.setdefault(cur_list_key, []).append(_parse_scalar(stripped[2:]))
            continue

        if ":" not in line:
            cur_list_key = None
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if not value:
            # 等下一行 '- item'
            cur_list_key = key
            out[key] = []
            continue

        cur_list_key = None
        if value.startswith("["):
            out[key] = _parse_inline_list(value)
        else:
            out[key] = _parse_scalar(value)
    return out


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 --- yaml --- frontmatter, 返回 (meta_dict, body).

    没有 frontmatter → ({}, original_text)。
    PyYAML 可用就用它, 否则走手写 parser。
    """
    if not text.startswith("---"):
        return {}, text
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    front_text, body = m.group(1), m.group(2)
    data = _try_yaml_load(front_text)
    if data is None:
        data = _hand_parse_frontmatter(front_text)
    if not isinstance(data, dict):
        data = {}
    return data, body


# ────────────── skill file parser ──────────────

def parse_skill_file(path: Path) -> Optional[MarkdownSkill]:
    """读 .md, 校验必填字段, 返回 MarkdownSkill. 失败 return None + log warning."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("[markdown_loader] 读 %s 失败: %s", path, e)
        return None

    meta, body = parse_frontmatter(text)
    body = (body or "").strip()
    if not body:
        logger.warning("[markdown_loader] %s: body 为空, 跳过", path.name)
        return None

    name = str(meta.get("name") or "").strip()
    if not name:
        logger.warning("[markdown_loader] %s: 缺少 name, 跳过", path.name)
        return None
    if not _KEBAB_RE.match(name):
        logger.warning(
            "[markdown_loader] %s: name '%s' 不是 kebab-case, 跳过", path.name, name,
        )
        return None

    description = str(meta.get("description") or "").strip()
    if not description:
        logger.warning("[markdown_loader] %s: 缺少 description, 跳过", path.name)
        return None

    # 选填: triggers / hook_points / priority / persona_role
    raw_triggers = meta.get("triggers") or []
    if isinstance(raw_triggers, str):
        raw_triggers = [raw_triggers]
    triggers = [str(t).strip() for t in raw_triggers if str(t).strip()]

    raw_hooks = meta.get("hook_points") or ["collab_respond"]
    if isinstance(raw_hooks, str):
        raw_hooks = [raw_hooks]
    hook_points = [str(h).strip() for h in raw_hooks if str(h).strip()]
    if not hook_points:
        hook_points = ["collab_respond"]

    raw_priority = meta.get("priority", 0)
    try:
        priority = int(raw_priority)
    except (TypeError, ValueError):
        priority = 0

    raw_role = str(meta.get("persona_role") or "system_prefix").strip().lower()
    if raw_role not in ("system_prefix", "system_suffix"):
        logger.warning(
            "[markdown_loader] %s: persona_role '%s' 非法, 用 system_prefix",
            path.name, raw_role,
        )
        raw_role = "system_prefix"

    return MarkdownSkill(
        name=name,
        description=description,
        body=body,
        source_path=str(path),
        triggers=triggers,
        hook_points=hook_points,
        priority=priority,
        persona_role=raw_role,
    )


# ────────────── directory loader ──────────────

def load_skills_from_dir(skill_dir: Path) -> list[MarkdownSkill]:
    """扫目录下所有 *.md, 返回 skill 列表. 目录不存在返回 []."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        return []
    out: list[MarkdownSkill] = []
    for md_path in sorted(skill_dir.glob("*.md")):
        skill = parse_skill_file(md_path)
        if skill:
            out.append(skill)
    return out


def load_all_markdown_skills(
    extra_dirs: Optional[list[Path]] = None,
) -> dict[str, MarkdownSkill]:
    """加载 DEFAULT_SKILL_DIRS + extra_dirs 所有 skill, 后加载覆盖前加载.

    返回 dict[name → MarkdownSkill]。重名时后者赢 (用户自定义可覆盖内置)。
    """
    dirs = list(DEFAULT_SKILL_DIRS) + list(extra_dirs or [])
    out: dict[str, MarkdownSkill] = {}
    for d in dirs:
        for skill in load_skills_from_dir(d):
            if skill.name in out:
                logger.info(
                    "[markdown_loader] '%s' 被 %s 覆盖 (原: %s)",
                    skill.name, skill.source_path, out[skill.name].source_path,
                )
            out[skill.name] = skill
    return out


# ────────────── registry integration ──────────────

# 进程级 cache: name → MarkdownSkill, 给 skill_injector.maybe_inject_skill 拿 body 用
_LOADED_SKILLS: dict[str, MarkdownSkill] = {}


def get_loaded_skills() -> dict[str, MarkdownSkill]:
    """skill_injector 用这个查 skill body. 被 register_markdown_skills 写入."""
    return _LOADED_SKILLS


def get_skill(name: str) -> Optional[MarkdownSkill]:
    return _LOADED_SKILLS.get(name)


async def register_markdown_skills(
    registry,
    extra_dirs: Optional[list[Path]] = None,
) -> int:
    """加载并注册到 SkillRegistry. 返回成功注册数量.

    每个 MarkdownSkill 会:
    1. 转成 SkillDefinition (skill_id=name, trigger=MANUAL)
    2. 包成 MarkdownSkillExecutor 注册到 registry
    3. 写进 _LOADED_SKILLS 供 skill_injector 查 body

    幂等: 重复调用安全 (registry.register 直接覆盖同名 entry)。
    """
    from app.harness.skill_registry import SkillDefinition, SkillTrigger
    from app.harness.skills.markdown_executor import MarkdownSkillExecutor

    skills = load_all_markdown_skills(extra_dirs=extra_dirs)
    _LOADED_SKILLS.clear()
    _LOADED_SKILLS.update(skills)

    registered = 0
    for name, skill in skills.items():
        executor = MarkdownSkillExecutor(skill)
        definition = SkillDefinition(
            skill_id=name,
            display_name=skill.description[:60] or name,
            description=skill.description,
            trigger=SkillTrigger.MANUAL,
            required_context=["base_system_prompt"],
            estimated_llm_calls=0,  # skill 本身不调 LLM, 只改 prompt
            estimated_duration_seconds=0,
            min_round=0,
        )
        try:
            registry.register(definition, executor.execute)
            registered += 1
        except Exception as e:
            logger.warning(
                "[markdown_loader] 注册 '%s' 失败: %s", name, e,
            )

    logger.info(
        "[markdown_loader] 共加载 %d 个 markdown skills (扫目录: %s)",
        registered,
        [str(d) for d in (list(DEFAULT_SKILL_DIRS) + list(extra_dirs or []))],
    )
    return registered
