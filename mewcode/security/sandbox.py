"""Path sandbox — validates file tool paths against project boundaries."""

from pathlib import Path


class PathSandbox:
    """Validates that file paths stay within allowed boundaries."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = (project_root or Path.cwd()).resolve()

    @property
    def project_root(self) -> Path:
        return self._project_root

    def validate(self, path: str) -> tuple[bool, str]:
        """Check whether *path* is safe to access.

        Returns:
            ``(is_safe, message)`` — ``is_safe`` is True when the path
            is within the project root and does not escape via ``..``.
        """
        p = Path(path)

        # Reject absolute paths that are outside project root
        if p.is_absolute():
            try:
                resolved = p.resolve(strict=False)
            except Exception:
                return False, f"无法解析路径: {path}"
            try:
                resolved.relative_to(self._project_root)
            except ValueError:
                return False, f"路径超出项目目录: {path}（绝对路径不在 {self._project_root} 内）"
            return True, ""

        # Relative path — resolve and check
        try:
            resolved = (self._project_root / p).resolve(strict=False)
        except Exception:
            return False, f"无效路径: {path}"

        try:
            resolved.relative_to(self._project_root)
        except ValueError:
            return False, f"路径遍历不被允许: {path}（解析后 {resolved} 不在项目目录内）"

        # Extra: check for suspicious .. in the relative path
        if ".." in Path(path).parts:
            return False, f"路径包含 '..' 不被允许: {path}"

        return True, ""

    def is_within_allowed(self, path: str, allowed_globs: list[str]) -> bool:
        """Check if *path* matches any of the allowed glob patterns."""
        import fnmatch
        for g in allowed_globs:
            if fnmatch.fnmatch(path, g):
                return True
        return False
