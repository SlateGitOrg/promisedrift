from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from promisedrift.engine import build_database
from promisedrift.export import export_star
from promisedrift.generator import DEFAULT_SEED, Tables, generate, write_tables

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def seed_data() -> tuple[Tables, dict]:
    return generate(DEFAULT_SEED)


@pytest.fixture(scope="session")
def seed_dir(tmp_path_factory: pytest.TempPathFactory, seed_data) -> Path:
    path = tmp_path_factory.mktemp("seed") / "raw"
    write_tables(path, seed_data[0])
    return path


@pytest.fixture(scope="session")
def seed_con(seed_dir: Path) -> duckdb.DuckDBPyConnection:
    return build_database(seed_dir)


@pytest.fixture(scope="session")
def seed_export(tmp_path_factory: pytest.TempPathFactory, seed_con) -> Path:
    out = tmp_path_factory.mktemp("export") / "data"
    export_star(seed_con, out)
    return out


@pytest.fixture
def pbip_copy(tmp_path: Path) -> Path:
    """A scratch copy of the committed Power BI project that tests may damage."""
    import shutil

    target = tmp_path / "powerbi"
    shutil.copytree(PROJECT_ROOT / "powerbi", target)
    return target
