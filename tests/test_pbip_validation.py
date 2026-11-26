"""validate-pbip on the committed project and on deliberately broken copies."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import PROJECT_ROOT
from promisedrift.metrics import METRIC_NAMES
from promisedrift.pbip import read_csv_table, validate_project
from promisedrift.schema import STAR, column_names
from promisedrift.tmdl import load_model

MODEL = "PromiseDrift.SemanticModel/definition"
FACT = f"{MODEL}/tables/fct_po_line_status.tmdl"


def _edit(project: Path, relative: str, old: str, new: str) -> None:
    path = project / relative
    text = path.read_text("utf-8")
    assert old in text, f"{old!r} not found in {relative}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _messages(project: Path) -> list[str]:
    return [str(i) for i in validate_project(project).issues]


def test_committed_project_passes():
    result = validate_project(PROJECT_ROOT / "powerbi")
    assert result.issues == []
    assert result.stats == {
        "tables": 4,
        "columns": sum(len(c) for c in STAR.values()),
        "measures": 9,
        "relationships": 4,
        "pages": 3,
        "visuals": 12,
    }


def test_measure_names_in_the_model_equal_the_registry():
    model = load_model(PROJECT_ROOT / "powerbi" / MODEL)
    names = [m for t in model.tables.values() for m in t.measures]
    assert sorted(names) == sorted(METRIC_NAMES)


def test_csv_headers_equal_tmdl_column_sets_for_every_table():
    model = load_model(PROJECT_ROOT / "powerbi" / MODEL)
    for name, table in model.tables.items():
        header = read_csv_table(PROJECT_ROOT / "powerbi" / "data" / f"{name}.csv").header
        assert {c.source_column for c in table.columns.values()} == set(header)
        assert header == column_names(name)


def test_every_relationship_one_side_key_is_unique_in_the_export():
    root = PROJECT_ROOT / "powerbi"
    model = load_model(root / MODEL)
    assert len(model.relationships) == 4
    for rel in model.relationships:
        values = read_csv_table(root / "data" / f"{rel.to_table}.csv").column(rel.to_column)
        assert len(values) == len(set(values)) and "" not in values


def test_measure_referencing_a_missing_column_fails_naming_measure_and_column(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "SUM ( fct_po_line_status[d1_otif] )",
        "SUM ( fct_po_line_status[promise_dt] )",
    )
    messages = _messages(pbip_copy)
    assert len(messages) == 1
    assert "OTIF Headline %" in messages[0]
    assert "fct_po_line_status[promise_dt]" in messages[0]


def test_measure_referencing_a_missing_measure_fails(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "COUNTROWS ( fct_po_line_status ) )\n\t\t\t```\n\t\tformatString: 0.0%\n\t\tlineageTag: ",
        "COUNTROWS ( fct_po_line_status ) ) + [No Such Measure]"
        "\n\t\t\t```\n\t\tformatString: 0.0%\n\t\tlineageTag: ",
    )
    assert any("[No Such Measure]" in m and "no such measure" in m for m in _messages(pbip_copy))


def test_deleting_a_registry_measure_fails(pbip_copy):
    path = pbip_copy / FACT
    text = path.read_text("utf-8")
    start = text.index("\tmeasure 'Bridge Early pp'")
    end = text.index("\tmeasure 'Bridge Re-promise pp'")
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    messages = _messages(pbip_copy)
    assert any("registry metric 'Bridge Early pp' has no measure" in m for m in messages)


def test_measure_outside_the_registry_fails(pbip_copy):
    _edit(pbip_copy, FACT, "measure 'Promise Drift Days'", "measure 'Promise Drift Days Avg'")
    messages = _messages(pbip_copy)
    assert any("'Promise Drift Days Avg' is not in the metric registry" in m for m in messages)
    assert any("registry metric 'Promise Drift Days' has no measure" in m for m in messages)


def test_column_missing_from_the_csv_header_fails(pbip_copy):
    path = pbip_copy / "data" / "dim_supplier.csv"
    lines = path.read_text("utf-8").splitlines()
    lines[0] = lines[0].replace("commodity", "category")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    messages = _messages(pbip_copy)
    assert any("column commodity is not in dim_supplier.csv" in m for m in messages)
    assert any("has column category the model does not declare" in m for m in messages)


def test_duplicate_one_side_key_fails(pbip_copy):
    path = pbip_copy / "data" / "dim_supplier.csv"
    lines = path.read_text("utf-8").splitlines()
    lines[2] = lines[2].replace("SUP-02", "SUP-01", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    messages = _messages(pbip_copy)
    assert any("one-side key is not unique" in m and "SUP-01" in m for m in messages)
    assert any("have no match" in m and "SUP-02" in m for m in messages)


def test_wrong_value_type_in_a_csv_column_fails(pbip_copy):
    path = pbip_copy / "data" / "fct_lead_time.csv"
    text = path.read_text("utf-8").splitlines()
    cells = text[1].split(",")
    cells[3] = "many"  # the `lines` column is int64
    text[1] = ",".join(cells)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    assert any("column lines is int64" in m for m in _messages(pbip_copy))


def test_m_query_type_that_disagrees_with_tmdl_fails(pbip_copy):
    _edit(
        pbip_copy,
        f"{MODEL}/tables/dim_supplier.tmdl",
        '{"supplier_name", type text}',
        '{"supplier_name", Int64.Type}',
    )
    assert any("supplier_name is string in TMDL but typed int64" in m for m in _messages(pbip_copy))


def test_report_visual_bound_to_a_missing_column_fails(pbip_copy):
    path = pbip_copy / "PromiseDrift.Report" / "report.json"
    text = path.read_text("utf-8")
    assert "supplier_name" in text
    path.write_text(text.replace("supplier_name", "supplier_title"), encoding="utf-8")
    messages = _messages(pbip_copy)
    assert any("binds to column dim_supplier[supplier_title]" in m for m in messages)


def test_report_with_wrong_pages_fails(pbip_copy):
    path = pbip_copy / "PromiseDrift.Report" / "report.json"
    report = json.loads(path.read_text("utf-8"))
    report["sections"].pop()
    path.write_text(json.dumps(report), encoding="utf-8")
    assert any("report pages are" in m for m in _messages(pbip_copy))


def test_report_must_reference_the_model_by_a_relative_path(pbip_copy):
    pbir = pbip_copy / "PromiseDrift.Report" / "definition.pbir"
    spec = json.loads(pbir.read_text("utf-8"))
    assert spec["datasetReference"]["byPath"]["path"] == "../PromiseDrift.SemanticModel"
    spec["datasetReference"]["byPath"]["path"] = "../Missing.SemanticModel"
    pbir.write_text(json.dumps(spec), encoding="utf-8")
    assert any("has no definition.pbism" in m for m in _messages(pbip_copy))


def test_missing_data_file_is_reported(pbip_copy):
    (pbip_copy / "data" / "fct_lead_time.csv").unlink()
    assert any("fct_lead_time.csv not found" in m for m in _messages(pbip_copy))


def test_data_folder_parameter_is_a_neutral_placeholder():
    text = (PROJECT_ROOT / "powerbi" / MODEL / "expressions.tmdl").read_text("utf-8")
    assert "expression DataFolder" in text
    assert not re.search(r"[/\\]Users[/\\]", text)


def test_measure_summing_the_wrong_flag_fails(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "SUM ( fct_po_line_status[d1_otif] )",
        "SUM ( fct_po_line_status[d3_otif] )",
    )
    messages = _messages(pbip_copy)
    assert len(messages) == 1
    assert "[dax-shape]" in messages[0] and "'OTIF Headline %'" in messages[0]
    assert "d1_otif" in messages[0]


def test_bridge_measure_summing_another_component_fails(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "SUM ( fct_po_line_status[bridge_early] )",
        "SUM ( fct_po_line_status[bridge_partial] )",
    )
    messages = _messages(pbip_copy)
    assert len(messages) == 1 and "'Bridge Early pp'" in messages[0]


def test_measure_with_the_wrong_aggregation_or_scale_fails(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "AVERAGE ( fct_po_line_status[drift_days] )",
        "SUM ( fct_po_line_status[drift_days] )",
    )
    _edit(
        pbip_copy,
        FACT,
        "100 * DIVIDE ( SUM ( fct_po_line_status[bridge_repromise] )",
        "DIVIDE ( SUM ( fct_po_line_status[bridge_repromise] )",
    )
    names = " ".join(_messages(pbip_copy))
    assert "'Promise Drift Days'" in names and "'Bridge Re-promise pp'" in names


def test_reformatting_a_measure_does_not_fail(pbip_copy):
    _edit(
        pbip_copy,
        FACT,
        "DIVIDE ( SUM ( fct_po_line_status[d2_otif] ), COUNTROWS ( fct_po_line_status ) )",
        "DIVIDE(SUM(fct_po_line_status[d2_otif]),\n\t\t\t\tCOUNTROWS(fct_po_line_status))",
    )
    assert _messages(pbip_copy) == []


def test_every_registry_metric_declares_its_dax_form():
    from promisedrift.metrics import METRICS, expected_dax

    for metric in METRICS:
        assert metric.table and metric.column and metric.dax_kind, metric.name
        assert expected_dax(metric).count(metric.column) == 1
