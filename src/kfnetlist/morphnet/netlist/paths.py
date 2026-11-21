"""File paths in netlists, the same on every OS (and the same as ``kfnetlist_schema::paths``).

The stored form is POSIX (``data/w.txt``): ``\\`` and ``/`` both separate, ``.`` and
``..`` resolve lexically (no filesystem, no symlinks), and ``/x``, ``C:/x``,
``C:\\x`` and ``\\\\server\\share`` are absolute on every host. A relative path stays
relative unless a ``base`` is given.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

__all__ = ["is_absolute", "posix_file", "resolve_file"]

DRIVE_RE = re.compile(r"[A-Za-z]:")


def _split(text: str) -> tuple[str, str]:
    """``(root, rest)``: ``//`` (UNC), ``C:`` / ``C:/`` (drive), ``/`` or ``""``."""
    text = text.replace("\\", "/")
    if text.startswith("//"):
        return "//", text[2:]
    if DRIVE_RE.match(text):
        root, rest = text[:2], text[2:]
        return (root + "/", rest[1:]) if rest.startswith("/") else (root, rest)
    if text.startswith("/"):
        return "/", text[1:]
    return "", text


def _text(path: str | PurePath) -> str:
    return path.as_posix() if isinstance(path, PurePath) else str(path)


def posix_file(path: str | PurePath) -> str:
    """``path`` in the stored form: POSIX separators, ``.``/``..`` resolved."""
    root, rest = _split(_text(path))
    parts: list[str] = []
    for seg in rest.split("/"):
        if seg in ("", "."):
            continue
        if seg != "..":
            parts.append(seg)
        elif parts and parts[-1] != "..":
            parts.pop()
        elif not root:  # above a relative start: kept; above a root: dropped
            parts.append("..")
    return root + "/".join(parts) or "."


def is_absolute(path: str | PurePath) -> bool:
    root = _split(_text(path))[0]
    return root in ("/", "//") or root.endswith(":/")


def resolve_file(path: str | PurePath, base: str | PurePath | None = None) -> Path:
    """``path`` joined to ``base`` when relative, in the stored form, as a ``Path``."""
    text = _text(path)
    if base is not None and not is_absolute(text):
        text = f"{_text(base)}/{text}"
    return Path(posix_file(text))
