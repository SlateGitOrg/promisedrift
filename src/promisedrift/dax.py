"""Extract the model references a DAX expression makes.

Three forms are recognised: `'Table Name'[Column]`, `Table[Column]` and a bare `[Measure]`. A
qualified reference may name a column or a measure of that table. The qualifier must touch the
bracket (`Table[Column]`), which is how DAX writers and Power BI itself format references; this
keeps keywords such as RETURN from being read as table names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_STRING = re.compile(r'"(?:[^"]|"")*"')
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?://|--)[^\n]*")
_QUALIFIED = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_]*))\[((?:[^\]]|\]\])+)\]")
_BARE = re.compile(r"\[((?:[^\]]|\]\])+)\]")


@dataclass(frozen=True)
class DaxRef:
    table: str | None  # None for a bare [Measure]
    name: str

    def __str__(self) -> str:
        if self.table is None:
            return f"[{self.name}]"
        quoted = f"'{self.table}'" if not re.fullmatch(r"[A-Za-z_]\w*", self.table) else self.table
        return f"{quoted}[{self.name}]"


def _strip_noise(dax: str) -> str:
    dax = _STRING.sub('""', dax)
    dax = _BLOCK_COMMENT.sub(" ", dax)
    return _LINE_COMMENT.sub(" ", dax)


def extract_refs(dax: str) -> list[DaxRef]:
    """Return every column or measure reference in the expression, in order, without repeats."""
    text = _strip_noise(dax)
    found: list[tuple[int, DaxRef]] = []
    for match in _QUALIFIED.finditer(text):
        table = (match.group(1) or match.group(2) or "").replace("''", "'")
        found.append((match.start(), DaxRef(table, match.group(3).replace("]]", "]"))))
    masked = _QUALIFIED.sub(lambda m: " " * len(m.group(0)), text)
    for match in _BARE.finditer(masked):
        found.append((match.start(), DaxRef(None, match.group(1).replace("]]", "]"))))
    refs: list[DaxRef] = []
    for _, ref in sorted(found, key=lambda item: item[0]):
        if ref not in refs:
            refs.append(ref)
    return refs
