"""TMDL parsing and DAX reference extraction."""

from __future__ import annotations

import pytest

from promisedrift.dax import DaxRef, extract_refs
from promisedrift.tmdl import (
    TmdlError,
    parse_expressions,
    parse_relationships,
    parse_table,
    split_dotted,
    split_name,
)

TABLE = "\n".join(
    [
        "table sales",
        "\tlineageTag: aaa",
        "",
        "\tcolumn id",
        "\t\tdataType: string",
        "\t\tsourceColumn: id",
        "",
        "\tcolumn 'Net Amount'",
        "\t\tdataType: double",
        "\t\tsourceColumn: net_amount",
        "",
        "\tmeasure 'Total: Net' = SUM ( sales[net_amount] )",
        "\t\tformatString: 0.0",
        "",
        "\tmeasure 'Share %' = ```",
        "\t\t\tDIVIDE ( [Total: Net], CALCULATE ( [Total: Net], ALL ( sales ) ) )",
        "\t\t\t```",
        "\t\tformatString: 0.0%",
        "",
        "\tpartition sales = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        '\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & "sales.csv"))',
        "\t\t\t\tin",
        "\t\t\t\t    Source",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
)


def test_parse_table_reads_columns_measures_and_partition():
    table = parse_table(TABLE)
    assert table.name == "sales"
    assert list(table.columns) == ["id", "Net Amount"]
    assert table.columns["Net Amount"].source_column == "net_amount"
    assert table.columns["Net Amount"].data_type == "double"
    assert table.measures["Total: Net"].expression == "SUM ( sales[net_amount] )"
    assert table.measures["Share %"].expression == (
        "DIVIDE ( [Total: Net], CALCULATE ( [Total: Net], ALL ( sales ) ) )"
    )
    assert len(table.partitions) == 1
    assert 'File.Contents(DataFolder & "sales.csv")' in table.partitions[0].source


def test_parse_relationships_and_expressions():
    rels = parse_relationships(
        "relationship abc\n\tfromColumn: fct.supplier_id\n\ttoColumn: 'Dim Supplier'.supplier_id\n"
    )
    assert (rels[0].from_table, rels[0].from_column) == ("fct", "supplier_id")
    assert (rels[0].to_table, rels[0].to_column) == ("Dim Supplier", "supplier_id")
    exprs = parse_expressions(
        'expression DataFolder = "C:\\data\\" meta [IsParameterQuery=true]\n\tlineageTag: x\n'
    )
    assert exprs["DataFolder"].startswith('"C:\\data\\"')


def test_names_with_quotes_and_dots():
    assert split_name("'It''s here' = 1") == ("It's here", "= 1")
    assert split_dotted("'My Table'.'my col'") == ("My Table", "my col")
    with pytest.raises(TmdlError):
        split_name("'unterminated")


def test_spaces_instead_of_tabs_are_rejected():
    with pytest.raises(TmdlError, match="tabs"):
        parse_table("table t\n    column a\n")


def test_unterminated_backtick_block_is_an_error():
    with pytest.raises(TmdlError, match="unterminated"):
        parse_table("table t\n\tmeasure m = ```\n\t\t\t1 + 1\n")


@pytest.mark.parametrize(
    ("dax", "expected"),
    [
        ("SUM ( fct[amount] )", [DaxRef("fct", "amount")]),
        ("SUM ( 'Fact Table'[Net Amount] )", [DaxRef("Fact Table", "Net Amount")]),
        ("DIVIDE ( [A], [B] )", [DaxRef(None, "A"), DaxRef(None, "B")]),
        ("100 * DIVIDE ( SUM ( f[x] ), [Count] )", [DaxRef("f", "x"), DaxRef(None, "Count")]),
        ('"fake[ref]" & f[real]', [DaxRef("f", "real")]),
        ("// note f[old]\nf[new] + f[new]", [DaxRef("f", "new")]),
        ("VAR x = 1 RETURN [Total]", [DaxRef(None, "Total")]),
        ("f[a]]b]", [DaxRef("f", "a]b")]),
    ],
)
def test_extract_refs(dax, expected):
    assert extract_refs(dax) == expected


def test_ref_formatting_quotes_only_when_needed():
    assert str(DaxRef("fct", "x")) == "fct[x]"
    assert str(DaxRef("Fact Table", "x")) == "'Fact Table'[x]"
    assert str(DaxRef(None, "Measure")) == "[Measure]"
