"""Bronze layer: load raw CSVs and seed files into DuckDB exactly as received.

Everything is read as VARCHAR so nothing is silently coerced or dropped at the
door. Typing and cleaning happen in the silver layer, where the decisions are
visible in SQL.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from src import config

log = logging.getLogger(__name__)


def load_bronze(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in config.RAW_TABLES:
        path = raw_dir / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file: {path}. Run `make data` first.")
        con.execute(
            f"""
            create or replace table bronze.{table} as
            select
                * exclude (filename),
                filename as _source_file,
                current_timestamp as _loaded_at
            from read_csv(?, header = true, all_varchar = true, filename = true)
            """,
            [str(path)],
        )
        counts[table] = con.execute(f"select count(*) from bronze.{table}").fetchone()[0]
        log.info("bronze.%-12s %8d rows", table, counts[table])
    return counts


def load_seeds(con: duckdb.DuckDBPyConnection, seeds_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(seeds_dir.glob("*.csv")):
        con.execute(
            f"create or replace table ref.{path.stem} as select * from read_csv(?, header = true, all_varchar = true)",
            [str(path)],
        )
        counts[path.stem] = con.execute(f"select count(*) from ref.{path.stem}").fetchone()[0]
        log.info("ref.%-15s %8d rows", path.stem, counts[path.stem])
    return counts
