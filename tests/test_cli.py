"""End-to-end CLI run in a scratch directory."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from conftest import PROJECT_ROOT
from promisedrift.cli import app

runner = CliRunner()


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    base = tmp_path_factory.mktemp("cli")
    steps = [
        ["generate", "--out", str(base / "data")],
        ["build", "--data", str(base / "data"), "--db", str(base / "db.duckdb")],
        ["export", "--db", str(base / "db.duckdb"), "--out", str(base / "star")],
    ]
    for args in steps:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    return base


def test_generate_build_export_produce_the_expected_files(workspace):
    assert sorted(p.name for p in (workspace / "data").iterdir()) == [
        "po_lines.csv",
        "promise_changes.csv",
        "receipts.csv",
        "suppliers.csv",
        "truth.json",
    ]
    assert (workspace / "db.duckdb").exists()
    assert sorted(p.name for p in (workspace / "star").iterdir()) == [
        "dim_date.csv",
        "dim_supplier.csv",
        "fct_lead_time.csv",
        "fct_po_line_status.csv",
    ]


def test_report_lists_top_suppliers_with_ranks_and_bridge(workspace):
    result = runner.invoke(app, ["report", "--db", str(workspace / "db.duckdb"), "--top", "3"])
    assert result.exit_code == 0
    assert "## Bridge from headline (D1) to first-confirmed (D3)" in result.output
    table_rows = [ln for ln in result.output.splitlines() if ln.startswith("| SUP-")]
    assert [ln.split("|")[1].split()[0] for ln in table_rows] == ["SUP-28", "SUP-19", "SUP-07"]
    assert "| 1 |" in table_rows[0]


def test_report_can_write_a_file(workspace):
    out = workspace / "report.md"
    result = runner.invoke(app, ["report", "--db", str(workspace / "db.duckdb"), "--out", str(out)])
    assert result.exit_code == 0
    text = out.read_text()
    assert text.count("| SUP-") == 35


def test_validate_pbip_exit_codes():
    ok = runner.invoke(app, ["validate-pbip", "--project", str(PROJECT_ROOT / "powerbi")])
    assert ok.exit_code == 0
    assert ok.output.startswith("OK: 4 tables")


def test_validate_pbip_fails_with_a_message_when_the_project_is_empty(tmp_path):
    bad = runner.invoke(app, ["validate-pbip", "--project", str(tmp_path)])
    assert bad.exit_code == 1
    assert "expected exactly one .pbip file" in bad.output
    assert "FAILED: 1 issue(s)" in bad.output


def test_build_without_raw_data_explains_what_to_run(tmp_path):
    result = runner.invoke(
        app, ["build", "--data", str(tmp_path / "nothing"), "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code != 0
    assert "promisedrift generate" in str(result.exception)
