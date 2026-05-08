class SandboxError(PermissionError):
    """Raised when a path escapes or violates sandbox policy."""


class ToolError(RuntimeError):
    """Raised when a file tool encounters an unexpected failure."""
