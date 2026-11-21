"""File paths in netlists, the same on every OS (and the same as ``kfnetlist_schema::paths``).

The stored form is POSIX (``data/w.txt``): ``\\`` and ``/`` both separate, ``.`` and
``..`` resolve lexically (no filesystem, no symlinks), and ``/x``, ``C:/x``,
``C:\\x``, ``C:x`` and ``\\\\server\\share`` are absolute on every host; ``..``
never climbs above a root (a drive, a share, ``/``). A relative path stays
relative unless a ``base`` is given.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

__all__ = ["is_absolute", "posix_file", "resolve_file"]

DRIVE_RE = re.compile(r"[A-Za-z]:")


def _split(text: str) -> tuple[str, str]:
    """``(root, rest)``. Every root is absolute: ``//server/share/`` (UNC: ``..``
    stops at the share), ``C:/`` (a drive letter is that drive's root, also in
    ``C:rel``), ``/`` (one, or three or more, slashes); ``""`` for a relative path."""
    text = text.replace("\\", "/")
    if text.startswith("//") and not text.startswith("///"):
        server, _, rest = text[2:].partition("/")
        share, _, rest = rest.partition("/")
        return f"//{server}/{share}/" if share else f"//{server}/", rest
    if DRIVE_RE.match(text):
        return text[:2] + "/", text[2:].lstrip("/")
    if text.startswith("/"):
        return "/", text.lstrip("/")
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
    return bool(_split(_text(path))[0])


def resolve_file(path: str | PurePath, base: str | PurePath | None = None) -> Path:
    """``path`` joined to ``base`` when relative, in the stored form, as a ``Path``."""
    text = _text(path)
    if base is not None and _text(base) and not is_absolute(text):  # "": no base
        text = f"{_text(base)}/{text}"
    return Path(posix_file(text))
