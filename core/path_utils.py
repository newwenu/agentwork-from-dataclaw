"""Unified sandboxed path resolution utilities.

All file-system tools should use ``resolve_under()`` to guarantee that
user-supplied paths cannot escape the configured root directory.
"""

from pathlib import Path


def resolve_under(root: Path | str, file_path: str, *, must_exist: bool = False) -> Path:
    """Resolve ``file_path`` to an absolute path strictly under ``root``.

    Rules:
        1. Reject null bytes.
        2. Normalize backslashes to forward slashes.
        3. Strip leading ``./``.
        4. Reject any ``..`` segment (leading or intermediate).
        5. If ``file_path`` is an absolute path already inside ``root``, use it.
           Otherwise treat it as relative to ``root``.
        6. The final resolved path must still be under ``root``.
        7. Reject symbolic links (both the final path and any parent).
        8. If ``must_exist`` is True, the path must exist.

    Args:
        root: Allowed root directory.
        file_path: User-supplied path (relative or absolute).
        must_exist: Whether to require the path to exist.

    Returns:
        A safe, resolved absolute Path.

    Raises:
        ValueError: If the path is illegal or escapes the root directory.
    """
    root = Path(root).resolve()

    if "\x00" in file_path:
        raise ValueError("Path contains null bytes")

    normalized = file_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]

    if normalized.startswith(".."):
        raise ValueError("Path escapes allowed directory")

    for segment in normalized.split("/"):
        if segment == "..":
            raise ValueError("Path escapes allowed directory")

    raw_path = Path(file_path).resolve()
    try:
        raw_path.relative_to(root)
        target = raw_path
    except ValueError:
        target = (root / normalized).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path escapes allowed directory") from exc

    # Reject symlinks: either the final path or any parent above root.
    if target.is_symlink() or any(
        part.is_symlink() for part in target.parents if part != root
    ):
        raise ValueError("Symlinks are not allowed")

    if must_exist and not target.exists():
        raise ValueError(f"File not found: {file_path}")

    return target
