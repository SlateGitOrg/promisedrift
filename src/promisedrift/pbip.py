"""Static validation of the Power BI project against the exported CSVs and the metric registry.

Power BI cannot run in CI, so this module reads the PBIP files as text and checks everything a
refresh or a render would trip over: every table loads a CSV that exists, the TMDL columns equal
the CSV header and their types match the data, every DAX reference resolves, relationship keys are
unique on the one side and present on the many side, the measure set equals the metric registry,
and every report visual binds to columns and measures that exist.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from promisedrift.dax import extract_refs
from promisedrift.metrics import METRIC_NAMES, METRICS, expected_dax
from promisedrift.tmdl import SemanticModel, TmdlError, load_model

REPORT_PAGES = ["Scorecard", "OTIF Bridge", "Supplier Drill"]

_M_TYPES = {
    "type text": "string",
    "Int64.Type": "int64",
    "type date": "dateTime",
    "type number": "double",
}
_CSV_FILE = re.compile(r'File\.Contents\(\s*DataFolder\s*&\s*"([^"]+)"\s*\)')
_M_COLUMN_TYPE = re.compile(r'\{\s*"([^"]+)"\s*,\s*(type \w+|Int64\.Type)\s*\}')
_EXAMPLES = 3


@dataclass(frozen=True)
class Issue:
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, code: str, message: str) -> None:
        self.issues.append(Issue(code, message))


@dataclass
class CsvTable:
    header: list[str]
    rows: list[list[str]]

    def column(self, name: str) -> list[str]:
        return [row[self.header.index(name)] for row in self.rows]


def read_csv_table(path: Path) -> CsvTable:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        return CsvTable(header, list(reader))


def validate_project(project_dir: Path, data_dir: Path | None = None) -> ValidationResult:
    """Validate the PBIP project in project_dir (the folder holding the .pbip file)."""
    result = ValidationResult()
    data_dir = data_dir or project_dir / "data"

    pbip_files = sorted(project_dir.glob("*.pbip"))
    if len(pbip_files) != 1:
        result.add(
            "structure",
            f"expected exactly one .pbip file in {project_dir}, found {len(pbip_files)}",
        )
        return result
    report_dir, model_dir = _resolve_artifacts(pbip_files[0], result)
    if model_dir is None:
        return result

    try:
        model = load_model(model_dir / "definition")
    except (TmdlError, OSError) as exc:
        result.add("tmdl", f"cannot read the semantic model: {exc}")
        return result

    csvs = _check_tables(model, data_dir, result)
    _check_measures(model, csvs, result)
    _check_relationships(model, csvs, result)
    if report_dir is not None:
        _check_report(report_dir, model, result)

    result.stats.update(
        tables=len(model.tables),
        columns=sum(len(t.columns) for t in model.tables.values()),
        measures=sum(len(t.measures) for t in model.tables.values()),
        relationships=len(model.relationships),
    )
    return result


def _resolve_artifacts(pbip: Path, result: ValidationResult) -> tuple[Path | None, Path | None]:
    try:
        spec = json.loads(pbip.read_text("utf-8"))
        report_rel = spec["artifacts"][0]["report"]["path"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        result.add("structure", f"{pbip.name} does not name a report: {exc!r}")
        return None, None
    report_dir = pbip.parent / report_rel
    pbir = report_dir / "definition.pbir"
    try:
        by_path = json.loads(pbir.read_text("utf-8"))["datasetReference"]["byPath"]["path"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        result.add("structure", f"{pbir} does not point at a semantic model by path: {exc!r}")
        return report_dir, None
    model_dir = (report_dir / by_path).resolve()
    if not (model_dir / "definition.pbism").exists():
        result.add("structure", f"{pbir.name} points at {by_path}, which has no definition.pbism")
        return report_dir, None
    if not (model_dir / "definition").is_dir():
        result.add("structure", f"{model_dir.name} has no definition/ folder")
        return report_dir, None
    return report_dir, model_dir


def _check_tables(
    model: SemanticModel, data_dir: Path, result: ValidationResult
) -> dict[str, CsvTable]:
    csvs: dict[str, CsvTable] = {}
    if sorted(model.ref_tables) != sorted(model.tables):
        result.add(
            "tmdl",
            f"model.tmdl refs {sorted(model.ref_tables)} "
            f"but tables/ defines {sorted(model.tables)}",
        )
    if "DataFolder" not in model.expressions:
        result.add("tmdl", "expressions.tmdl does not define the DataFolder parameter")

    for table in model.tables.values():
        if len(table.partitions) != 1:
            result.add(
                "partition",
                f"table {table.name}: expected one partition, found {len(table.partitions)}",
            )
            continue
        source = table.partitions[0].source
        match = _CSV_FILE.search(source)
        if not match:
            result.add(
                "partition", f"table {table.name}: partition does not load a CSV from DataFolder"
            )
            continue
        path = data_dir / match.group(1)
        if not path.exists():
            result.add("partition", f"table {table.name}: {match.group(1)} not found in {data_dir}")
            continue
        csv_table = read_csv_table(path)
        csvs[table.name] = csv_table

        model_cols = {c.source_column for c in table.columns.values()}
        header = set(csv_table.header)
        for missing in sorted(model_cols - header):
            result.add("csv-columns", f"table {table.name}: column {missing} is not in {path.name}")
        for extra in sorted(header - model_cols):
            result.add(
                "csv-columns",
                f"table {table.name}: {path.name} has column {extra} the model does not declare",
            )

        m_types = dict(_M_COLUMN_TYPE.findall(source))
        for col in table.columns.values():
            expected = _M_TYPES.get(m_types.get(col.source_column, ""))
            if expected is None:
                result.add(
                    "m-types",
                    f"table {table.name}: M query does not type column {col.source_column}",
                )
            elif expected != col.data_type:
                result.add(
                    "m-types",
                    f"table {table.name}: column {col.name} is {col.data_type} in TMDL "
                    f"but typed {expected} in the M query",
                )
            if col.source_column in header:
                _check_values(
                    table.name, col.name, col.data_type, csv_table, col.source_column, result
                )
    return csvs


def _check_values(
    table: str,
    column: str,
    dtype: str | None,
    csv_table: CsvTable,
    source: str,
    result: ValidationResult,
) -> None:
    parsers = {
        "int64": int,
        "double": float,
        "dateTime": lambda v: date.fromisoformat(v[:10]),
    }
    parse = parsers.get(dtype or "")
    if parse is None:
        return
    bad: list[str] = []
    for value in csv_table.column(source):
        if value == "":
            continue
        try:
            parse(value)
        except ValueError:
            bad.append(value)
    if bad:
        result.add(
            "csv-type",
            f"table {table}: column {column} is {dtype} "
            f"but has {len(bad)} values such as {bad[:_EXAMPLES]}",
        )


def _check_measures(
    model: SemanticModel, csvs: dict[str, CsvTable], result: ValidationResult
) -> None:
    measures = {m.name: m for t in model.tables.values() for m in t.measures.values()}
    registry = set(METRIC_NAMES)
    for name in sorted(registry - set(measures)):
        result.add("measure-set", f"registry metric {name!r} has no measure in the model")
    for name in sorted(set(measures) - registry):
        result.add("measure-set", f"measure {name!r} is not in the metric registry")

    by_name = {m.name: m for m in METRICS}
    for measure in measures.values():
        unresolved = False
        for ref in extract_refs(measure.expression):
            problem = _resolve_ref(model, csvs, measures, ref.table, ref.name)
            if problem:
                unresolved = True
                result.add("dax-ref", f"measure {measure.name!r} references {ref}: {problem}")
        metric = by_name.get(measure.name)
        if metric is None or unresolved:
            continue
        # References resolve; now check the measure aggregates the column the registry names.
        found = "".join(measure.expression.split())
        expected = expected_dax(metric)
        if found != expected:
            result.add(
                "dax-shape",
                f"measure {measure.name!r} is {measure.expression.strip()!r} but the registry "
                f"defines it as {expected!r} (whitespace ignored)",
            )


def _resolve_ref(
    model: SemanticModel,
    csvs: dict[str, CsvTable],
    measures: dict[str, Any],
    table: str | None,
    name: str,
) -> str | None:
    if table is None:
        return None if name in measures else "no such measure in the model"
    tbl = model.tables.get(table)
    if tbl is None:
        return f"table {table} is not in the model"
    if name in tbl.measures:
        return None
    col = tbl.columns.get(name)
    if col is None:
        return f"{table} has no column or measure {name}"
    csv_table = csvs.get(table)
    if csv_table is not None and col.source_column not in csv_table.header:
        return f"column {name} is not in the exported CSV for {table}"
    return None


def _check_relationships(
    model: SemanticModel, csvs: dict[str, CsvTable], result: ValidationResult
) -> None:
    for rel in model.relationships:
        label = f"{rel.from_table}[{rel.from_column}] -> {rel.to_table}[{rel.to_column}]"
        ends = []
        for table, column in ((rel.from_table, rel.from_column), (rel.to_table, rel.to_column)):
            col = model.tables[table].columns.get(column) if table in model.tables else None
            if col is None:
                result.add(
                    "relationship", f"{label}: {table}[{column}] is not a column of the model"
                )
            ends.append(col)
        if None in ends:
            continue
        if ends[0].data_type != ends[1].data_type:
            result.add(
                "relationship",
                f"{label}: key types differ ({ends[0].data_type} vs {ends[1].data_type})",
            )
        one, many = csvs.get(rel.to_table), csvs.get(rel.from_table)
        if one is None or many is None:
            continue
        one_values = one.column(ends[1].source_column)
        if "" in one_values:
            result.add("relationship", f"{label}: the one-side key has blank values")
        counts = Counter(one_values)
        dupes = sorted(v for v, n in counts.items() if n > 1)
        if dupes:
            result.add(
                "relationship",
                f"{label}: the one-side key is not unique, e.g. {dupes[:_EXAMPLES]}",
            )
        known = set(one_values)
        orphans = sorted({v for v in many.column(ends[0].source_column) if v and v not in known})
        if orphans:
            result.add(
                "relationship",
                f"{label}: {len(orphans)} many-side values have no match, "
                f"e.g. {orphans[:_EXAMPLES]}",
            )


def _check_report(report_dir: Path, model: SemanticModel, result: ValidationResult) -> None:
    path = report_dir / "report.json"
    try:
        report = json.loads(path.read_text("utf-8"))
        sections = report["sections"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        result.add("report", f"cannot read {path}: {exc!r}")
        return
    pages = [s.get("displayName") for s in sections]
    if pages != REPORT_PAGES:
        result.add("report", f"report pages are {pages}, expected {REPORT_PAGES}")
    visuals = 0
    for section in sections:
        page = section.get("displayName", "?")
        containers = section.get("visualContainers", [])
        if not containers:
            result.add("report", f"page {page!r} has no visuals")
        for container in containers:
            visuals += 1
            _check_visual(page, container, model, result)
    result.stats["pages"] = len(sections)
    result.stats["visuals"] = visuals


def _check_visual(
    page: str, container: dict[str, Any], model: SemanticModel, result: ValidationResult
) -> None:
    try:
        config = json.loads(container["config"])
        single = config["singleVisual"]
        query = single["prototypeQuery"]
        aliases = {f["Name"]: f["Entity"] for f in query["From"]}
        selects = query["Select"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        result.add("report", f"page {page!r}: a visual has no readable query: {exc!r}")
        return
    where = f"page {page!r} visual {config.get('name', '?')!r}"
    select_names: set[str] = set()
    for item in selects:
        kind = "Column" if "Column" in item else "Measure" if "Measure" in item else None
        if kind is None:
            result.add(
                "report",
                f"{where}: select item {item.get('Name')!r} is neither a column nor a measure",
            )
            continue
        select_names.add(item["Name"])
        field_ = item[kind]
        alias = field_["Expression"]["SourceRef"]["Source"]
        entity, prop = aliases.get(alias), field_["Property"]
        table = model.tables.get(entity or "")
        if table is None:
            result.add("report", f"{where}: binds to table {entity!r}, which is not in the model")
        elif kind == "Column" and prop not in table.columns:
            result.add(
                "report", f"{where}: binds to column {entity}[{prop}], which is not in the model"
            )
        elif kind == "Measure" and prop not in table.measures:
            result.add(
                "report", f"{where}: binds to measure {entity}[{prop}], which is not in the model"
            )
    for role, projections in single.get("projections", {}).items():
        for projection in projections:
            if projection["queryRef"] not in select_names:
                result.add(
                    "report",
                    f"{where}: {role} projection {projection['queryRef']!r} is not in the query",
                )
