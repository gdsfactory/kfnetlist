from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from kfnetlist.morphnet.netlist.hdl import apply_defines
from kfnetlist.morphnet.netlist.vams.preprocess import (
    BLOCK_COMMENT_RE,
    DIRECTIVE_RE,
    LINE_COMMENT_RE,
)

# (* attr = value *) — but not the `@(*)` event control
ATTRIBUTE_RE: re.Pattern[str] = re.compile(r"\(\*(?!\s*\)).*?\*\)", re.DOTALL)

# Constructs that are not netlist structure. Matched left to right, so a
# construct nested in an earlier one is consumed with it.
CONSTRUCT_RE: re.Pattern[str] = re.compile(
    r"\b(always_comb|always_ff|always_latch|always|initial|final|assign|"
    r"assert|assume|cover|typedef|import|export|genvar|timeunit|timeprecision|"
    r"defparam|specparam|(?:virtual\s+)?class|function|task|generate|covergroup|"
    r"property|sequence|clocking|specify|interface|package|program|primitive)\b"
)
END_KEYWORDS: dict[str, str] = {
    "class": "endclass",
    "function": "endfunction",
    "task": "endtask",
    "generate": "endgenerate",
    "covergroup": "endgroup",
    "property": "endproperty",
    "sequence": "endsequence",
    "clocking": "endclocking",
    "specify": "endspecify",
    "interface": "endinterface",
    "package": "endpackage",
    "program": "endprogram",
    "primitive": "endprimitive",
}
PROCEDURAL = {"always", "always_comb", "always_ff", "always_latch", "initial", "final"}
DROPPED = {"typedef", "import", "export", "genvar", "timeunit", "timeprecision"}

NET_REF = r"(?:\\\S+|[A-Za-z_][\w$]*)(?:\s*\[[^\]]*\])*"
SIMPLE_ASSIGN_RE: re.Pattern[str] = re.compile(
    rf"assign\s+{NET_REF}\s*=\s*{NET_REF}(?:\s*,\s*{NET_REF}\s*=\s*{NET_REF})*\s*;"
)

TOKEN_RE: re.Pattern[str] = re.compile(r"\s*(@\*|[A-Za-z_][\w$]*|.)", re.DOTALL)
SEMI_SCAN_RE: re.Pattern[str] = re.compile(r'"(?:\\.|[^"\\])*"|[(\[{]|[)\]}]|;')
LABEL_RE: re.Pattern[str] = re.compile(r"\s*:\s*[A-Za-z_][\w$]*")
GROUP_ATOM_RE: re.Pattern[str] = re.compile(r"\s*[\w$.']+")


@dataclass
class SvPreprocessResult:
    text: str
    directives: list[tuple[str, str]] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)


def preprocess_systemverilog(
    text: str, defines: Mapping[str, str] | None = None
) -> SvPreprocessResult:
    """Prepare SystemVerilog text for Lark parsing.

    1. Strip block comments, line comments and ``(* attributes *)``.
    2. Keep the active `` `ifdef `` branches for ``defines``, expand macros, then
       extract backtick directives (`include, `define, `timescale, etc.).
    3. Replace behavioral constructs (always, initial, function, task, generate,
       class, non-trivial assign, ...) with ``__sv_placeholder__ N ;`` markers.
       typedef / import / genvar / timeunit statements are dropped.
    """
    text = BLOCK_COMMENT_RE.sub("", text)
    text = LINE_COMMENT_RE.sub("", text)
    text = ATTRIBUTE_RE.sub("", text)
    text = apply_defines(text, defines)

    directives = [(m.group(1), m.group(2).strip()) for m in DIRECTIVE_RE.finditer(text)]
    text = DIRECTIVE_RE.sub("", text)

    text, blocks = replace_behavioral_blocks(text)

    text = re.sub(r"\n{2,}", "\n", text).strip()
    if text:
        text += "\n"
    return SvPreprocessResult(text=text, directives=directives, blocks=blocks)


def replace_behavioral_blocks(text: str) -> tuple[str, list[str]]:
    """Replace non-structural constructs with numbered placeholder tokens."""
    blocks: list[str] = []
    out: list[str] = []
    i = 0
    while (m := CONSTRUCT_RE.search(text, i)) is not None:
        kw = m.group(1).split()[-1]
        if kw in END_KEYWORDS:
            end = _match_end(text, m.end(), kw, END_KEYWORDS[kw])
        elif kw in PROCEDURAL:
            end = _skip_statement(text, m.end())
        else:
            end = _skip_to_semicolon(text, m.end())
        stmt = text[m.start() : end]
        out.append(text[i : m.start()])
        if kw == "assign" and SIMPLE_ASSIGN_RE.fullmatch(stmt):
            out.append(stmt)
        elif kw not in DROPPED:
            out.append(f" __sv_placeholder__ {len(blocks)} ;")
            blocks.append(stmt.strip())
        i = end
    out.append(text[i:])
    return "".join(out), blocks


def _skip_to_semicolon(text: str, i: int) -> int:
    """Index just past the next ``;`` outside brackets and strings."""
    depth = 0
    for m in SEMI_SCAN_RE.finditer(text, i):
        tok = m.group()
        if tok == ";" and depth == 0:
            return m.end()
        if tok in "([{":
            depth += 1
        elif tok in ")]}":
            depth -= 1
    return len(text)


def _match_end(text: str, i: int, open_kw: str, close_kw: str) -> int:
    """Index just past the ``close_kw`` (and optional ``: label``) matching an open."""
    depth = 1
    for m in re.finditer(rf"\b({open_kw})\b|\b({close_kw})\b", text[i:]):
        depth += 1 if m.group(1) else -1
        if depth == 0:
            end = i + m.end()
            label = LABEL_RE.match(text, end)
            return label.end() if label else end
    return len(text)


def _skip_group(text: str, i: int) -> int:
    """Skip ``(...)`` or a single atom (``#10``, ``@clk``)."""
    j = len(text) - len(text[i:].lstrip())
    if text[j : j + 1] != "(":
        m = GROUP_ATOM_RE.match(text, i)
        return m.end() if m else i
    depth = 0
    for k in range(j, len(text)):
        depth += {"(": 1, ")": -1}.get(text[k], 0)
        if depth == 0:
            return k + 1
    return len(text)


def _skip_statement(text: str, i: int) -> int:
    """Index just past one procedural statement starting at ``i``."""
    m = TOKEN_RE.match(text, i)
    if m is None:
        return len(text)
    tok, j = m.group(1), m.end()
    if tok == "begin":
        return _match_end(text, j, "begin", "end")
    if tok == "fork":
        return _match_end(text, j, "fork", "join|join_any|join_none")
    if tok in ("case", "casex", "casez", "randcase"):
        return _match_end(text, j, "case|casex|casez|randcase", "endcase")
    if tok in ("@", "#"):
        return _skip_statement(text, _skip_group(text, j))
    if tok in ("@*", "unique", "priority", "forever"):
        return _skip_statement(text, j)
    if tok in ("for", "foreach", "while", "repeat", "wait"):
        return _skip_statement(text, _skip_group(text, j))
    if tok == "do":
        return _skip_to_semicolon(text, _skip_statement(text, j))
    if tok == "if":
        end = _skip_statement(text, _skip_group(text, j))
        nxt = TOKEN_RE.match(text, end)
        if nxt is not None and nxt.group(1) == "else":
            return _skip_statement(text, nxt.end())
        return end
    return _skip_to_semicolon(text, i)
