from __future__ import annotations

import os
from pathlib import Path

from .errors import SandboxError


class PathSandbox:
    """
    Per-project file sandbox. All paths are resolved relative to base_dir.

    Ported from Claude Code's expandPath + realpath + UNC check pattern.
    """

    def __init__(self, project_id: str, base_dir: Path | None = None) -> None:
        root = base_dir or Path(
            os.environ.get("PROJECT_WORKSPACE_DIR", "/app/data/projects")
        )
        self.project_id = project_id
        self.base_dir = (root / project_id).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel_path: str) -> Path:
        """Resolve `rel_path` to an absolute Path, rejecting escapes."""
        if "\x00" in rel_path:
            raise SandboxError("null byte in path")
        if rel_path.startswith(("\\\\", "//")):
            raise SandboxError("UNC path not allowed")

        candidate = (self.base_dir / rel_path).resolve()
        try:
            candidate.relative_to(self.base_dir)
        except ValueError as e:
            raise SandboxError(f"path escapes sandbox: {rel_path}") from e
        return candidate

    def read_text(self, rel_path: str, encoding: str = "utf-8") -> str:
        return self.resolve(rel_path).read_text(encoding=encoding)

    def write_text(
        self, rel_path: str, content: str, encoding: str = "utf-8"
    ) -> None:
        path = self.resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)

    def glob(self, pattern: str) -> list[Path]:
        return sorted(self.base_dir.glob(pattern))

    def exists(self, rel_path: str) -> bool:
        try:
            return self.resolve(rel_path).exists()
        except SandboxError:
            return False
