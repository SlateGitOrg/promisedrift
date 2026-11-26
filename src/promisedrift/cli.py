"""Command line interface: generate, build, export, validate-pbip, report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from promisedrift.engine import build_database
from promisedrift.export import export_star
from promisedrift.generator import DEFAULT_SEED, write_tables
from promisedrift.generator import generate as generate_data
from promisedrift.pbip import validate_project
from promisedrift.report import render_report

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Supplier OTIF under four definitions, with an exact bridge from the ERP headline.",
)

DataDir = Annotated[Path, typer.Option("--data", help="Directory with the raw CSV tables.")]
DbPath = Annotated[Path, typer.Option("--db", help="DuckDB database written by `build`.")]


@app.command()
def generate(
    seed: Annotated[int, typer.Option(help="Random seed.")] = DEFAULT_SEED,
    out: Annotated[Path, typer.Option(help="Output directory for the raw CSVs.")] = Path("data"),
) -> None:
    """Write synthetic suppliers, PO lines, promise changes and receipts."""
    tables, truth = generate_data(seed)
    write_tables(out, tables)
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    counts = ", ".join(f"{len(rows):,} {name}" for name, rows in tables.items())
    typer.echo(f"Wrote {counts} to {out}/")


@app.command()
def build(
    data: DataDir = Path("data"),
    db: DbPath = Path("build/promisedrift.duckdb"),
) -> None:
    """Load the raw CSVs into DuckDB and run the SQL reference."""
    con = build_database(data, db)
    lines = con.execute("SELECT count(*) FROM line_status").fetchone()[0]
    con.close()
    typer.echo(f"Built {db} with {lines:,} PO lines")


@app.command()
def export(
    db: DbPath = Path("build/promisedrift.duckdb"),
    out: Annotated[Path, typer.Option(help="Directory for the star-schema CSVs.")] = Path(
        "powerbi/data"
    ),
) -> None:
    """Write the star-schema CSVs the Power BI model loads."""
    con = duckdb.connect(str(db), read_only=True)
    counts = export_star(con, out)
    con.close()
    for table, rows in counts.items():
        typer.echo(f"{table}.csv  {rows:,} rows")


@app.command("validate-pbip")
def validate_pbip(
    project: Annotated[Path, typer.Option(help="Folder holding the .pbip file.")] = Path("powerbi"),
) -> None:
    """Check the PBIP model and report against the exported CSVs and the metric registry."""
    result = validate_project(project)
    if result.ok:
        s = result.stats
        typer.echo(
            f"OK: {s['tables']} tables, {s['columns']} columns, {s['measures']} measures, "
            f"{s['relationships']} relationships, {s['pages']} pages, {s['visuals']} visuals"
        )
        return
    for issue in result.issues:
        typer.echo(str(issue), err=True)
    typer.echo(f"FAILED: {len(result.issues)} issue(s)", err=True)
    raise typer.Exit(1)


@app.command()
def report(
    db: DbPath = Path("build/promisedrift.duckdb"),
    top: Annotated[int | None, typer.Option(help="List only the top N suppliers by D1.")] = None,
    out: Annotated[Path | None, typer.Option(help="Write to a file instead of stdout.")] = None,
) -> None:
    """Print the Markdown scorecard with D1 and D3 ranks and each supplier's bridge."""
    con = duckdb.connect(str(db), read_only=True)
    text = render_report(con, top=top)
    con.close()
    if out is None:
        typer.echo(text)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {out}")


if __name__ == "__main__":
    app()
