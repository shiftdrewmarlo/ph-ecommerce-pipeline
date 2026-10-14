from __future__ import annotations

from types import SimpleNamespace

import duckdb
import pytest

from src import config, pipeline


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """Run the whole pipeline once on a small dataset; expose paths and the run summary."""
    base = tmp_path_factory.mktemp("wh")
    db_path = base / "test.duckdb"
    raw_dir = base / "raw"
    summary = pipeline.run(db_path=db_path, raw_dir=raw_dir, regenerate=True, n_orders=3_000, n_customers=400, seed=7)
    return SimpleNamespace(db_path=db_path, raw_dir=raw_dir, summary=summary)


@pytest.fixture(scope="session")
def built_warehouse(build):
    """Read-only connection to the warehouse produced by the `build` fixture."""
    con = duckdb.connect(str(build.db_path), read_only=True)
    yield con
    con.close()


@pytest.fixture()
def mem():
    """In-memory DuckDB with the schemas + macros, for testing single SQL files in isolation."""
    con = duckdb.connect(":memory:")
    con.execute((config.SQL_DIR / "00_schemas.sql").read_text())
    yield con
    con.close()
