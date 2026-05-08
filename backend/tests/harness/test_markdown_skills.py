"""SKILL.md 系统 smoke tests.

覆盖:
- parse_frontmatter 各种边界 (无 frontmatter / 错误格式 / list 字段)
- parse_skill_file 必填校验 (name / description / body)
- load_skills_from_dir 不存在目录 → []
- maybe_inject_skill 三种优先级路径 (explicit / triggers / 都没命中)
- MarkdownSkillExecutor.compose 注入位置正确 (prefix vs suffix)
- hook_point 不匹配时不注入

不依赖 DB / Redis / LLM, 纯函数级验证。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.harness.skills import markdown_loader as ml
from app.harness.skills.markdown_executor import MarkdownSkillExecutor
from app.harness.skills.skill_injector import maybe_inject_skill


# ────────────────────── frontmatter parser ──────────────────────

class TestParseFrontmatter:
    def test_no_frontmatter_returns_empty_meta(self):
        text = "# Hello\n\nbody only"
        meta, body = ml.parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_frontmatter_with_inline_list(self):
        text = """---
name: test-skill
triggers: [a, b, c]
priority: 5
---
# body
"""
        meta, body = ml.parse_frontmatter(text)
        assert meta["name"] == "test-skill"
        assert meta["triggers"] == ["a", "b", "c"]
        assert meta["priority"] == 5
        assert "# body" in body

    def test_frontmatter_with_quoted_strings(self):
        text = """---
name: 'quoted-name'
description: "with: colon inside"
---
body
"""
        meta, _ = ml.parse_frontmatter(text)
        assert meta["name"] == "quoted-name"
        assert meta["description"] == "with: colon inside"

    def test_malformed_frontmatter_no_closing(self):
        # 没有结束 --- → regex 不匹配, 返回原 text 作 body
        text = "---\nname: x\nno closing"
        meta, body = ml.parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_frontmatter_multiline_list(self):
        text = """---
triggers:
  - alpha
  - beta
  - gamma
name: multi-list
---
body"""
        meta, _ = ml.parse_frontmatter(text)
        assert meta["triggers"] == ["alpha", "beta", "gamma"]
        assert meta["name"] == "multi-list"

    def test_frontmatter_inline_comment_stripped(self):
        text = """---
name: cmt-test  # this is a comment
priority: 7 # another
---
body"""
        meta, _ = ml.parse_frontmatter(text)
        assert meta["name"] == "cmt-test"
        assert meta["priority"] == 7


# ────────────────────── parse_skill_file ──────────────────────

class TestParseSkillFile:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_valid_skill_file(self, tmp_path):
        p = self._write(tmp_path, "ok.md", """---
name: my-skill
description: A test skill
triggers: [foo, bar]
hook_points: [collab_respond]
priority: 3
persona_role: system_prefix
---
This is the body. It should not be empty.
""")
        skill = ml.parse_skill_file(p)
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.description == "A test skill"
        assert skill.triggers == ["foo", "bar"]
        assert skill.hook_points == ["collab_respond"]
        assert skill.priority == 3
        assert skill.persona_role == "system_prefix"
        assert "This is the body" in skill.body

    def test_missing_name_returns_none(self, tmp_path):
        p = self._write(tmp_path, "no_name.md", """---
description: missing name
---
body
""")
        assert ml.parse_skill_file(p) is None

    def test_missing_description_returns_none(self, tmp_path):
        p = self._write(tmp_path, "no_desc.md", """---
name: x
---
body
""")
        assert ml.parse_skill_file(p) is None

    def test_invalid_kebab_case_name_rejected(self, tmp_path):
        p = self._write(tmp_path, "bad.md", """---
name: BadName_Snake
description: ok
---
body
""")
        assert ml.parse_skill_file(p) is None

    def test_empty_body_rejected(self, tmp_path):
        p = self._write(tmp_path, "empty.md", """---
name: empty-body
description: ok
---
""")
        assert ml.parse_skill_file(p) is None

    def test_default_hook_points_when_omitted(self, tmp_path):
        p = self._write(tmp_path, "default_hooks.md", """---
name: defhooks
description: tests defaults
---
body content
""")
        skill = ml.parse_skill_file(p)
        assert skill is not None
        assert skill.hook_points == ["collab_respond"]
        assert skill.persona_role == "system_prefix"
        assert skill.priority == 0
        assert skill.triggers == []

    def test_string_triggers_normalized_to_list(self, tmp_path):
        p = self._write(tmp_path, "str_trig.md", """---
name: str-trig
description: tests
triggers: single-trigger
---
body
""")
        skill = ml.parse_skill_file(p)
        assert skill is not None
        assert skill.triggers == ["single-trigger"]

    def test_invalid_persona_role_falls_back_to_prefix(self, tmp_path):
        p = self._write(tmp_path, "bad_role.md", """---
name: bad-role
description: ok
persona_role: weird_value
---
body
""")
        skill = ml.parse_skill_file(p)
        assert skill is not None
        assert skill.persona_role == "system_prefix"


# ────────────────────── load_skills_from_dir ──────────────────────

class TestLoadSkillsFromDir:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        fake = tmp_path / "nope"
        assert ml.load_skills_from_dir(fake) == []

    def test_file_not_dir_returns_empty(self, tmp_path):
        f = tmp_path / "notdir.md"
        f.write_text("hi", encoding="utf-8")
        assert ml.load_skills_from_dir(f) == []

    def test_loads_multiple_md_files(self, tmp_path):
        for i, name in enumerate(["alpha", "beta", "gamma"]):
            (tmp_path / f"{name}.md").write_text(f"""---
name: {name}
description: skill {i}
---
body of {name}
""", encoding="utf-8")
        skills = ml.load_skills_from_dir(tmp_path)
        assert len(skills) == 3
        names = sorted(s.name for s in skills)
        assert names == ["alpha", "beta", "gamma"]

    def test_skips_invalid_files(self, tmp_path):
        # 一个 valid + 一个 missing name
        (tmp_path / "ok.md").write_text("""---
name: good
description: yes
---
body
""", encoding="utf-8")
        (tmp_path / "bad.md").write_text("""---
description: no name
---
body
""", encoding="utf-8")
        skills = ml.load_skills_from_dir(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "good"

    def test_load_all_overrides(self, tmp_path):
        d1 = tmp_path / "d1"; d1.mkdir()
        d2 = tmp_path / "d2"; d2.mkdir()
        (d1 / "x.md").write_text("""---
name: shared
description: from d1
---
old body
""", encoding="utf-8")
        (d2 / "x.md").write_text("""---
name: shared
description: from d2
---
new body
""", encoding="utf-8")
        # 模拟 d2 在 d1 之后, 应该覆盖
        out = {}
        for d in (d1, d2):
            for s in ml.load_skills_from_dir(d):
                out[s.name] = s
        assert out["shared"].description == "from d2"


# ────────────────────── MarkdownSkillExecutor ──────────────────────

class TestMarkdownSkillExecutor:
    def _skill(self, **overrides) -> ml.MarkdownSkill:
        defaults = dict(
            name="t-skill",
            description="d",
            body="SKILL_BODY_HERE",
            source_path="/tmp/x.md",
            triggers=["foo"],
            hook_points=["collab_respond"],
            priority=0,
            persona_role="system_prefix",
        )
        defaults.update(overrides)
        return ml.MarkdownSkill(**defaults)

    @pytest.mark.asyncio
    async def test_prefix_role_puts_body_first(self):
        skill = self._skill(persona_role="system_prefix")
        ex = MarkdownSkillExecutor(skill)
        result = await ex.execute({
            "hook_point": "collab_respond",
            "base_system_prompt": "BASE_PROMPT",
        })
        assert result["skill_applied"] is True
        out = result["injected_prompt"]
        assert out.index("SKILL_BODY_HERE") < out.index("BASE_PROMPT")

    @pytest.mark.asyncio
    async def test_suffix_role_puts_base_first(self):
        skill = self._skill(persona_role="system_suffix")
        ex = MarkdownSkillExecutor(skill)
        result = await ex.execute({
            "hook_point": "collab_respond",
            "base_system_prompt": "BASE_PROMPT",
        })
        out = result["injected_prompt"]
        assert out.index("BASE_PROMPT") < out.index("SKILL_BODY_HERE")

    @pytest.mark.asyncio
    async def test_hook_point_mismatch_no_inject(self):
        skill = self._skill(hook_points=["scoring"])
        ex = MarkdownSkillExecutor(skill)
        result = await ex.execute({
            "hook_point": "collab_respond",
            "base_system_prompt": "BASE",
        })
        assert result["skill_applied"] is False
        assert result["injected_prompt"] == "BASE"

    @pytest.mark.asyncio
    async def test_wildcard_hook_matches_anything(self):
        skill = self._skill(hook_points=["*"])
        ex = MarkdownSkillExecutor(skill)
        result = await ex.execute({
            "hook_point": "anything",
            "base_system_prompt": "BASE",
        })
        assert result["skill_applied"] is True


# ────────────────────── maybe_inject_skill ──────────────────────

@pytest.fixture
def loaded_skills(monkeypatch):
    """注入两个 fake skills 到 _LOADED_SKILLS, 测完清空."""
    skill_a = ml.MarkdownSkill(
        name="alpha",
        description="alpha skill",
        body="ALPHA_BODY",
        source_path="/tmp/a.md",
        triggers=["综述", "review"],
        hook_points=["collab_respond"],
        priority=10,
        persona_role="system_prefix",
    )
    skill_b = ml.MarkdownSkill(
        name="bravo",
        description="bravo skill",
        body="BRAVO_BODY",
        source_path="/tmp/b.md",
        triggers=["竞品", "对比"],
        hook_points=["collab_respond", "summary"],
        priority=5,
        persona_role="system_suffix",
    )
    skill_low = ml.MarkdownSkill(
        name="low-pri",
        description="lower priority overlap",
        body="LOW_BODY",
        source_path="/tmp/c.md",
        triggers=["综述"],  # 与 alpha 重叠, 但 priority 更低
        hook_points=["collab_respond"],
        priority=1,
        persona_role="system_prefix",
    )
    fake = {"alpha": skill_a, "bravo": skill_b, "low-pri": skill_low}
    monkeypatch.setattr(ml, "_LOADED_SKILLS", fake)
    yield fake


class TestMaybeInjectSkill:
    @pytest.mark.asyncio
    async def test_no_skills_loaded_returns_unchanged(self, monkeypatch):
        monkeypatch.setattr(ml, "_LOADED_SKILLS", {})
        out, info = await maybe_inject_skill("BASE", "collab_respond")
        assert out == "BASE"
        assert info["applied"] is False

    @pytest.mark.asyncio
    async def test_explicit_skill_id_wins(self, loaded_skills):
        out, info = await maybe_inject_skill(
            "BASE", "collab_respond", explicit_skill_id="bravo",
        )
        assert info["applied"] is True
        assert info["skill_name"] == "bravo"
        # bravo 是 suffix → BASE 在前
        assert out.index("BASE") < out.index("BRAVO_BODY")

    @pytest.mark.asyncio
    async def test_triggers_match_picks_highest_priority(self, loaded_skills):
        # "综述" 同时命中 alpha (priority=10) 和 low-pri (priority=1) → alpha 赢
        out, info = await maybe_inject_skill(
            "BASE", "collab_respond",
            triggers_seen=["写一下综述部分"],
        )
        assert info["applied"] is True
        assert info["skill_name"] == "alpha"
        assert "ALPHA_BODY" in out

    @pytest.mark.asyncio
    async def test_no_match_returns_unchanged(self, loaded_skills):
        out, info = await maybe_inject_skill(
            "BASE", "collab_respond",
            triggers_seen=["完全不相关的输入"],
        )
        assert out == "BASE"
        assert info["applied"] is False

    @pytest.mark.asyncio
    async def test_explicit_id_wrong_hook_falls_through(self, loaded_skills):
        # alpha 只允许 collab_respond, 在 summary 应失效
        out, info = await maybe_inject_skill(
            "BASE", "summary", explicit_skill_id="alpha",
        )
        assert out == "BASE"
        assert info["applied"] is False

    @pytest.mark.asyncio
    async def test_explicit_id_overrides_triggers(self, loaded_skills):
        # triggers_seen 命中 alpha, 但 explicit 选 bravo → bravo 赢
        out, info = await maybe_inject_skill(
            "BASE", "collab_respond",
            explicit_skill_id="bravo",
            triggers_seen=["写综述"],
        )
        assert info["applied"] is True
        assert info["skill_name"] == "bravo"

    @pytest.mark.asyncio
    async def test_unknown_explicit_id_falls_back_to_triggers(self, loaded_skills):
        out, info = await maybe_inject_skill(
            "BASE", "collab_respond",
            explicit_skill_id="does-not-exist",
            triggers_seen=["综述"],
        )
        assert info["applied"] is True
        assert info["skill_name"] == "alpha"

    @pytest.mark.asyncio
    async def test_summary_hook_only_picks_compatible_skill(self, loaded_skills):
        # alpha 只允许 collab_respond, bravo 允许 summary → 综述 trigger 命中 alpha 但 hook 不匹配, 应空
        # 唯一匹配 summary hook + 命中 trigger 的: bravo (竞品/对比)
        out, info = await maybe_inject_skill(
            "BASE", "summary",
            triggers_seen=["综述"],   # 只有 alpha 的 trigger, 但 alpha 不接 summary
        )
        # alpha 不接 summary, low-pri 也不接 → 没匹配
        assert info["applied"] is False

        # 换成 "竞品" → bravo 接 summary → 命中
        out2, info2 = await maybe_inject_skill(
            "BASE", "summary",
            triggers_seen=["做个竞品分析"],
        )
        assert info2["applied"] is True
        assert info2["skill_name"] == "bravo"
