"""A small parser for the TMDL subset used by this semantic model.

TMDL is indentation-based: an object is a keyword and a name, its properties are `key: value`
lines one tab deeper, and an expression follows `=` either inline, inside a triple-backtick block,
or as an indented block. The parser reads tables, columns, measures, partitions, relationships and
expressions, which is everything `validate-pbip` needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class TmdlError(ValueError):
    """Raised when a TMDL file cannot be parsed."""


@dataclass
class Node:
    kind: str
    name: str
    value: str | None
    indent: int
    line: int
    children: list[Node] = field(default_factory=list)

    def prop(self, key: str) -> str | None:
        for child in self.children:
            if child.kind == "prop" and child.name == key:
                return child.value
        return None


@dataclass
class Column:
    name: str
    data_type: str | None
    source_column: str


@dataclass
class Measure:
    name: str
    expression: str
    table: str


@dataclass
class Partition:
    name: str
    source: str


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    measures: dict[str, Measure] = field(default_factory=dict)
    partitions: list[Partition] = field(default_factory=list)


@dataclass
class Relationship:
    name: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    active: bool = True


@dataclass
class SemanticModel:
    tables: dict[str, Table] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    expressions: dict[str, str] = field(default_factory=dict)
    ref_tables: list[str] = field(default_factory=list)


_PROP = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*:\s*(.*)$")
_BLOCK_PROP = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*=\s*(.*)$")
_OBJECT = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s+(.*)$")


def split_name(text: str) -> tuple[str, str]:
    """Split a leading TMDL name (bare or 'quoted') from the rest of the line."""
    text = text.lstrip()
    if text.startswith("'"):
        i = 1
        out: list[str] = []
        while i < len(text):
            if text[i] == "'":
                if text[i + 1 : i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), text[i + 1 :].strip()
            out.append(text[i])
            i += 1
        raise TmdlError(f"unterminated quoted name: {text!r}")
    match = re.match(r"[^\s=:.]+", text)
    if not match:
        raise TmdlError(f"expected a name at: {text!r}")
    return match.group(0), text[match.end() :].strip()


def split_dotted(text: str) -> tuple[str, str]:
    """Split `Table.column` (either side may be quoted) into its two names."""
    table, rest = split_name(text)
    if not rest.startswith("."):
        raise TmdlError(f"expected Table.column, got {text!r}")
    column, tail = split_name(rest[1:])
    if tail:
        raise TmdlError(f"unexpected text after column name: {text!r}")
    return table, column


def parse_nodes(text: str) -> list[Node]:
    """Parse indentation into a tree of nodes (objects, properties and expression bodies)."""
    lines = text.splitlines()
    root = Node("root", "", None, -1, 0)
    stack = [root]
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.strip().startswith("///"):
            continue
        body = raw.lstrip("\t")
        indent = len(raw) - len(body)
        if body.startswith(" "):
            raise TmdlError(f"line {i}: TMDL indents with tabs, found spaces")
        while stack[-1].indent >= indent:
            stack.pop()
        parent = stack[-1]

        prop = _PROP.match(body)
        block = _BLOCK_PROP.match(body)
        if prop:
            node = Node("prop", prop.group(1), prop.group(2).strip(), indent, i)
            parent.children.append(node)
            continue
        if block and block.group(1) == "source":
            node = Node("prop", block.group(1), block.group(2).strip(), indent, i)
            value, i = _read_body(lines, i, indent, node.value or "")
            node.value = value
            parent.children.append(node)
            continue

        obj = _OBJECT.match(body)
        if not obj:
            # Bare keyword lines (for example `discourageImplicitMeasures`) carry no data.
            parent.children.append(Node("flag", body.strip(), None, indent, i))
            continue
        kind, rest = obj.group(1), obj.group(2)
        name, tail = split_name(rest) if kind != "annotation" else (rest.split("=")[0].strip(), "")
        value: str | None = None
        if kind == "annotation":
            value = rest.split("=", 1)[1].strip() if "=" in rest else None
        elif tail.startswith("="):
            value, i = _read_body(lines, i, indent, tail[1:].strip())
        elif tail:
            value = tail
        node = Node(kind, name, value, indent, i)
        parent.children.append(node)
        stack.append(node)
    return root.children


def _read_body(lines: list[str], i: int, indent: int, first: str) -> tuple[str, int]:
    """Read an expression that starts after `=` on line i-1; return its text and the next index."""
    if first.startswith("```"):
        collected = [first[3:]] if first[3:].strip() else []
        while i < len(lines):
            current = lines[i]
            i += 1
            if current.strip() == "```":
                return "\n".join(s.strip() for s in collected).strip(), i
            collected.append(current)
        raise TmdlError("unterminated ``` block")
    if first:
        return first, i
    collected = []
    while i < len(lines):
        current = lines[i]
        if current.strip() and len(current) - len(current.lstrip("\t")) < indent + 2:
            break
        collected.append(current)
        i += 1
    return "\n".join(c.strip() for c in collected).strip(), i


def parse_table(text: str) -> Table:
    nodes = [n for n in parse_nodes(text) if n.kind == "table"]
    if len(nodes) != 1:
        raise TmdlError(f"expected exactly one table, found {len(nodes)}")
    node = nodes[0]
    table = Table(node.name)
    for child in node.children:
        if child.kind == "column":
            source = child.prop("sourceColumn") or child.name
            table.columns[child.name] = Column(child.name, child.prop("dataType"), source)
        elif child.kind == "measure":
            table.measures[child.name] = Measure(child.name, child.value or "", node.name)
        elif child.kind == "partition":
            table.partitions.append(Partition(child.name, child.prop("source") or ""))
    return table


def parse_relationships(text: str) -> list[Relationship]:
    out: list[Relationship] = []
    for node in parse_nodes(text):
        if node.kind != "relationship":
            continue
        frm, to = node.prop("fromColumn"), node.prop("toColumn")
        if frm is None or to is None:
            raise TmdlError(f"relationship {node.name}: fromColumn and toColumn are required")
        from_table, from_column = split_dotted(frm)
        to_table, to_column = split_dotted(to)
        active = (node.prop("isActive") or "true").lower() != "false"
        out.append(Relationship(node.name, from_table, from_column, to_table, to_column, active))
    return out


def parse_expressions(text: str) -> dict[str, str]:
    return {n.name: n.value or "" for n in parse_nodes(text) if n.kind == "expression"}


def load_model(definition_dir: Path) -> SemanticModel:
    """Read a `definition/` folder: model.tmdl, expressions.tmdl, relationships.tmdl, tables/."""
    model = SemanticModel()
    model_file = definition_dir / "model.tmdl"
    for node in parse_nodes(model_file.read_text("utf-8")):
        if node.kind == "ref" and node.name == "table" and node.value:
            model.ref_tables.append(split_name(node.value)[0])
    expressions_file = definition_dir / "expressions.tmdl"
    if expressions_file.exists():
        model.expressions = parse_expressions(expressions_file.read_text("utf-8"))
    relationships_file = definition_dir / "relationships.tmdl"
    if relationships_file.exists():
        model.relationships = parse_relationships(relationships_file.read_text("utf-8"))
    for path in sorted((definition_dir / "tables").glob("*.tmdl")):
        table = parse_table(path.read_text("utf-8"))
        model.tables[table.name] = table
    return model
