"""Pre-build docs source: jupytext .py → executed .md + downloadable .ipynb.

Replaces runtime mkdocs plugins (mkdocs-jupyter, mkdocs-gen-files) with
deterministic file generation into a staging directory. The static-site
generator (mkdocs or zensical) then sees only plain .md + assets.

Pipeline per source tree:
    docs/source/**/*.md   → copy verbatim to docs/source-built/
    docs/source/**/*.py   → jupytext.read → nbconvert.execute →
                            MarkdownExporter (+ TagRemovePreprocessor)
                            → docs/source-built/<path>.md  +
                              docs/source-built/<path>.ipynb (download)
                              + extracted output images
    docs/source/_static   → copy verbatim
    src/kfnetlist/**/*.py → docs/source-built/reference/**/*.md
                            (mkdocstrings ::: directive stubs)

Cache: docs/.build-cache/manifest.json keyed by content hash; unchanged
inputs skip re-execution.

Usage:
    python docs/scripts/build_docs_source.py
        [--source docs/source] [--out docs/source-built]
        [--cache docs/.build-cache] [--workers N] [--no-execute]
        [--clean]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import jupytext
import nbformat
from nbconvert import MarkdownExporter
from nbconvert.preprocessors import ExecutePreprocessor
from traitlets.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def cache_load(cache_dir: Path) -> dict[str, str]:
    f = cache_dir / "manifest.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return {}


def cache_save(cache_dir: Path, manifest: dict[str, str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )


def cache_key(input_path: Path, *output_paths: Path) -> str:
    return f"{input_path}::{':'.join(str(p) for p in output_paths)}"


_PY_LINK_RE = re.compile(r"(\]\((?!https?://)[^)]+?)\.py(#[^)]*)?\)")


def rewrite_py_links(text: str) -> str:
    """Rewrite Markdown links from foo.py → foo.md (skips http(s) URLs)."""
    return _PY_LINK_RE.sub(lambda m: f"{m.group(1)}.md{m.group(2) or ''})", text)


def fence_indented_blocks(text: str) -> str:
    """Convert nbconvert's indented (4-space) code blocks to fenced ```text
    blocks. Zensical's CommonMark parser incorrectly parses reference-style
    links inside indented blocks, but respects fenced blocks.
    """
    out: list[str] = []
    lines = text.splitlines(keepends=False)
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if (
            not in_fence
            and line.startswith("    ")
            and (i == 0 or lines[i - 1].strip() == "")
        ):
            block: list[str] = []
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("    "):
                    block.append(cur[4:])
                    i += 1
                elif cur.strip() == "":
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines) and lines[j].startswith("    "):
                        block.append("")
                        i += 1
                    else:
                        break
                else:
                    break
            out.append("```text")
            out.extend(block)
            out.append("```")
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def copy_md(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text()
    new = rewrite_py_links(text)
    if new == text:
        shutil.copy2(src, dst)
    else:
        dst.write_text(new)


def copy_static(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        return
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)


def is_jupytext_notebook(path: Path) -> bool:
    """Detect jupytext percent-format .py by header signature."""
    if path.suffix != ".py":
        return False
    try:
        head = path.read_text(errors="replace").splitlines()[:20]
    except OSError:
        return False
    return any(line.strip().startswith("# %%") for line in head) or any(
        "jupytext:" in line for line in head
    )


def convert_notebook(
    src: Path,
    src_root: Path,
    out_root: Path,
    *,
    execute: bool = True,
    timeout: int = 600,
) -> tuple[Path, Path]:
    """Convert a jupytext .py to executed .ipynb + .md.

    Returns (md_path, ipynb_path).
    """
    rel = src.relative_to(src_root)
    md_out = out_root / rel.with_suffix(".md")
    assets_dir = md_out.with_suffix("")
    assets_dir.mkdir(parents=True, exist_ok=True)
    ipynb_out = assets_dir / f"{rel.stem}.ipynb"
    md_out.parent.mkdir(parents=True, exist_ok=True)

    nb = jupytext.read(src, fmt="py:percent")
    if "kernelspec" not in nb.metadata:
        nb.metadata["kernelspec"] = {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }

    if execute:
        ep = ExecutePreprocessor(timeout=timeout, kernel_name="python3")
        ep.preprocess(nb, {"metadata": {"path": str(src.parent)}})

    nbformat.write(nb, ipynb_out)

    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            data = out.get("data") or {}
            has_fallback = "text/plain" in data or any(
                k.startswith("image/") for k in data
            )
            if has_fallback:
                for k in ("text/html", "text/latex"):
                    data.pop(k, None)

    cfg = Config()
    cfg.TagRemovePreprocessor.remove_input_tags = ("hide", "hide-input")
    cfg.TagRemovePreprocessor.remove_all_outputs_tags = ("hide", "hide-output")
    cfg.TagRemovePreprocessor.enabled = True
    cfg.MarkdownExporter.preprocessors = [
        "nbconvert.preprocessors.TagRemovePreprocessor"
    ]

    exporter = MarkdownExporter(config=cfg)
    body, resources = exporter.from_notebook_node(nb)

    outputs: dict[str, bytes] = resources.get("outputs", {}) or {}
    for name, data in outputs.items():
        (assets_dir / name).write_bytes(data)
    for name in outputs:
        body = body.replace(f"]({name})", f"]({assets_dir.name}/{name})")

    body = rewrite_py_links(body)
    body = fence_indented_blocks(body)

    download_btn = (
        f"[:material-download: Download notebook (.ipynb)]"
        f"({assets_dir.name}/{ipynb_out.name}){{ .md-button }}\n\n"
    )
    md_out.write_text(download_btn + body)
    return md_out, ipynb_out


def gen_api_reference(out_root: Path, src_pkg: Path) -> list[Path]:
    """Mirror src/kfnetlist/**/*.py to out_root/reference/**/*.md with
    mkdocstrings ::: directive stubs.

    URL layout (drops the redundant `kfnetlist/` prefix):
        kfnetlist/__init__.py          → reference/index.md
        kfnetlist/port_check.py        → reference/port_check.md
        kfnetlist/extract/__init__.py  → reference/extract/index.md
    """
    written: list[Path] = []
    api_tree: list[tuple[int, str, str]] = []

    for py in sorted(src_pkg.rglob("*.py")):
        rel = py.relative_to(src_pkg.parent)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__main__":
            continue
        if parts[-1].startswith("_") and parts[-1] != "__init__":
            continue
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
            sub_parts = parts[1:]
            doc_rel = (
                Path("index.md") if not sub_parts else Path(*sub_parts) / "index.md"
            )
        else:
            sub_parts = parts[1:]
            doc_rel = Path(*sub_parts).with_suffix(".md")
        target = out_root / "reference" / doc_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        ident = ".".join(parts)
        if is_package:
            target.write_text(f"::: {ident}\n    options:\n      members: false\n")
        else:
            target.write_text(f"::: {ident}\n")
        written.append(target)
        depth = max(len(parts) - 1, 0)
        title = parts[-1] if parts else "kfnetlist"
        api_tree.append((depth, title, doc_rel.as_posix()))

    api_nav_yaml = _api_tree_to_yaml(api_tree, indent=10)
    (out_root / "_api_nav.yml").write_text(api_nav_yaml)
    return written


def _api_tree_to_yaml(tree: list[tuple[int, str, str]], indent: int = 0) -> str:
    n = len(tree)
    is_pkg = [i + 1 < n and tree[i + 1][0] > tree[i][0] for i in range(n)]
    pad = " " * indent
    lines: list[str] = []
    for i, (depth, title, doc_rel) in enumerate(tree):
        col = pad + ("    " * max(0, depth - 1))
        link = f"reference/{doc_rel}"
        if depth == 0 and is_pkg[i]:
            lines.append(f"{col}- Overview: {link}")
        elif is_pkg[i]:
            lines.append(f"{col}- {title}:")
            lines.append(f"{col}    - Overview: {link}")
        else:
            lines.append(f"{col}- {title}: {link}")
    return "\n".join(lines) + "\n"


def splice_zensical_config(
    src_yml: Path, out_yml: Path, api_nav_fragment: Path
) -> None:
    """Replace `- API: reference/   # SPLICE_API` in src_yml with the
    generated API nav fragment, written to out_yml.
    """
    text = src_yml.read_text()
    marker_re = re.compile(
        r"^([ \t]*)- API:[ \t]*reference/[ \t]*#[ \t]*SPLICE_API[ \t]*$",
        re.MULTILINE,
    )
    match = marker_re.search(text)
    if not match:
        raise RuntimeError(
            f"Could not find `# SPLICE_API` marker in {src_yml}; the "
            "API nav block won't be auto-generated. Add the marker back "
            "or update the regex in build_docs_source.py."
        )
    indent = match.group(1)
    fragment = api_nav_fragment.read_text().rstrip("\n")
    spliced = f"{indent}- API:\n{fragment}"
    out_yml.write_text(marker_re.sub(spliced, text, count=1))


def process_one(args: tuple[Path, Path, Path, bool, int]) -> dict[str, Any]:
    src, src_root, out_root, execute, timeout = args
    t0 = time.perf_counter()
    md, ipynb = convert_notebook(
        src, src_root, out_root, execute=execute, timeout=timeout
    )
    return {
        "src": str(src),
        "md": str(md),
        "ipynb": str(ipynb),
        "elapsed": time.perf_counter() - t0,
        "hash": file_hash(src),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(REPO_ROOT / "docs/source"))
    parser.add_argument("--out", default=str(REPO_ROOT / "docs/source-built"))
    parser.add_argument("--cache", default=str(REPO_ROOT / "docs/.build-cache"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Only convert notebooks whose path contains this substring",
    )
    args = parser.parse_args(argv)

    src_root = Path(args.source).resolve()
    out_root = Path(args.out).resolve()
    cache_dir = Path(args.cache).resolve()

    if args.clean and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    manifest = cache_load(cache_dir)
    new_manifest = dict(manifest)

    # Stage 1: copy .md files
    md_count = 0
    for md in src_root.rglob("*.md"):
        rel = md.relative_to(src_root)
        copy_md(md, out_root / rel)
        md_count += 1

    # Stage 1b: copy static asset directories
    for static_dir in src_root.rglob("_static"):
        if static_dir.is_dir():
            rel = static_dir.relative_to(src_root)
            copy_static(static_dir, out_root / rel)

    # Stage 2: jupytext .py → .md + .ipynb
    notebooks = [p for p in src_root.rglob("*.py") if is_jupytext_notebook(p)]
    if args.only:
        notebooks = [p for p in notebooks if any(s in str(p) for s in args.only)]

    work: list[tuple[Path, Path, Path, bool, int]] = []
    skipped = 0
    for nb in notebooks:
        h = file_hash(nb)
        key = cache_key(nb, out_root)
        if manifest.get(key) == h:
            rel = nb.relative_to(src_root)
            md_path = out_root / rel.with_suffix(".md")
            ipynb_path = md_path.with_suffix("") / f"{rel.stem}.ipynb"
            if md_path.exists() and ipynb_path.exists():
                skipped += 1
                new_manifest[key] = h
                continue
        work.append((nb, src_root, out_root, not args.no_execute, args.timeout))

    print(
        f"[stage1] copied {md_count} .md files",
        f"[stage2] {len(work)} notebooks to convert ({skipped} cached)",
        sep="\n",
        flush=True,
    )

    failures: list[tuple[Path, BaseException]] = []
    if work:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_one, w): w[0] for w in work}
            for fut in concurrent.futures.as_completed(futures):
                src = futures[fut]
                try:
                    res = fut.result()
                    new_manifest[cache_key(Path(res["src"]), out_root)] = res["hash"]
                    print(
                        f"  ✓ {Path(res['src']).relative_to(src_root)} "
                        f"({res['elapsed']:.1f}s)",
                        flush=True,
                    )
                except BaseException as e:  # noqa: BLE001
                    failures.append((src, e))
                    print(f"  ✗ {src.relative_to(src_root)}: {e}", flush=True)

    # Stage 3: API reference
    print("[stage3] generating API reference …", flush=True)
    ref_files = gen_api_reference(out_root, REPO_ROOT / "src" / "kfnetlist")
    print(f"  wrote {len(ref_files)} reference pages", flush=True)

    # Stage 3.5: splice API nav into zensical.yml → docs/zensical-built.yml
    src_cfg = REPO_ROOT / "docs/zensical.yml"
    spliced_cfg = REPO_ROOT / "docs/zensical-built.yml"
    fragment = out_root / "_api_nav.yml"
    splice_zensical_config(src_cfg, spliced_cfg, fragment)
    print(f"[stage3.5] wrote {spliced_cfg.relative_to(REPO_ROOT)}", flush=True)

    cache_save(cache_dir, new_manifest)

    if failures:
        print(f"\n{len(failures)} notebook(s) failed:", file=sys.stderr)
        for src, e in failures:
            print(f"  {src}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
