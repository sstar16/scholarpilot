from __future__ import annotations

from pathlib import Path

import pytest

from app.harness.file_tools.errors import SandboxError
from app.harness.file_tools.sandbox import PathSandbox


class TestPathSandbox:
    def test_resolve_inside_base_dir(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        result = sb.resolve("literature/foo.md")
        assert result == (sandbox_dir / "proj1" / "literature" / "foo.md").resolve()

    def test_resolve_rejects_parent_escape(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        with pytest.raises(SandboxError, match="escapes sandbox"):
            sb.resolve("../../etc/passwd")

    def test_resolve_rejects_null_byte(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        with pytest.raises(SandboxError, match="null byte"):
            sb.resolve("literature/foo\x00bar.md")

    def test_resolve_rejects_unc_path(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        with pytest.raises(SandboxError, match="UNC path"):
            sb.resolve("\\\\server\\share\\file")

    def test_write_and_read_text(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        sb.write_text("notes/hello.md", "Hello, 世界")
        assert sb.read_text("notes/hello.md") == "Hello, 世界"

    def test_write_creates_parent_dirs(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        sb.write_text("deeply/nested/path/file.md", "data")
        assert (sandbox_dir / "proj1" / "deeply" / "nested" / "path" / "file.md").exists()

    def test_glob_only_inside_base(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        sb.write_text("literature/a.md", "a")
        sb.write_text("literature/b.md", "b")
        sb.write_text("notes/c.md", "c")
        matches = sb.glob("literature/*.md")
        names = sorted(p.name for p in matches)
        assert names == ["a.md", "b.md"]

    def test_exists_false_on_escape(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("proj1", base_dir=sandbox_dir)
        assert sb.exists("../outside.md") is False

    def test_base_dir_auto_created(self, sandbox_dir: Path) -> None:
        sb = PathSandbox("new_proj", base_dir=sandbox_dir)
        assert sb.base_dir.exists()
        assert sb.base_dir == (sandbox_dir / "new_proj").resolve()
