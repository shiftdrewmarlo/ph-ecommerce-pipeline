"""Pipeline orchestrator: generate -> bronze -> silver -> gold -> data quality.

Run:  python -m src.pipeline            # use existing raw files (generates them if missing)
      python -m src.pipeline --regenerate --orders 40000
The pipeline is a full refresh and idempotent: running it twice gives the same warehouse.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb

from src import config, generate_data, ingest, quality

log = logging.getLogger("pipeline")


def _sql_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.sql"))


@contextmanager
def _step(con: duckdb.DuckDBPyConnection, run_id: str, name: str):
    started = datetime.now()
    t0 = time.perf_counter()
    log.info("▶ %s", name)
    try:
        yield
    except Exception as exc:
        con.execute("insert into ops.run_log values (?, ?, ?, ?, 'failed', ?)",
                    [run_id, name, started, time.perf_counter() - t0, str(exc)[:500]])
        raise
    dur = time.perf_counter() - t0
    con.execute("insert into ops.run_log values (?, ?, ?, ?, 'success', null)", [run_id, name, started, dur])
    log.info("✔ %s (%.2fs)", name, dur)


def run(
    db_path: Path = config.DB_PATH,
    raw_dir: Path = config.RAW_DIR,
    regenerate: bool = False,
    n_orders: int = config.DEFAULT_ORDERS,
    n_customers: int = config.DEFAULT_CUSTOMERS,
    seed: int = config.DEFAULT_SEED,
    skip_dq: bool = False,
) -> dict:
    run_id = uuid.uuid4().hex[:12]
    db_path.parent.mkdir(parents=True, exist_ok=True)

    needs_data = regenerate or not all((raw_dir / f"{t}.csv").exists() for t in config.RAW_TABLES)
    if needs_data:
        log.info("▶ generating raw data (orders=%d, seed=%d)", n_orders, seed)
        generate_data.generate(raw_dir, n_orders, n_customers, seed)

    con = duckdb.connect(str(db_path))
    try:
        con.execute((config.SQL_DIR / "00_schemas.sql").read_text())

        with _step(con, run_id, "bronze: load raw files + seeds"):
            ingest.load_bronze(con, raw_dir)
            ingest.load_seeds(con, config.SEEDS_DIR)

        for layer in ("silver", "gold"):
            for sql_file in _sql_files(config.SQL_DIR / layer):
                with _step(con, run_id, f"{layer}: {sql_file.name}"):
                    con.execute(sql_file.read_text())

        results: list[dict] = []
        if not skip_dq:
            with _step(con, run_id, "data quality checks"):
                results = quality.run_checks(con, run_id)
            quality.enforce(results)

        summary = {
            "run_id": run_id,
            "checks_passed": sum(r["status"] == "pass" for r in results),
            "checks_failed": sum(r["status"] == "fail" for r in results),
            "rows": {
                t: con.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("silver.orders", "silver.rejected_orders", "gold.fact_orders", "gold.fact_order_items")
            },
        }
        log.info("done: %s", summary)
        return summary
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--regenerate", action="store_true", help="regenerate synthetic raw data first")
    p.add_argument("--orders", type=int, default=config.DEFAULT_ORDERS)
    p.add_argument("--customers", type=int, default=config.DEFAULT_CUSTOMERS)
    p.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    p.add_argument("--db", type=Path, default=config.DB_PATH)
    p.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    p.add_argument("--skip-dq", action="store_true")
    args = p.parse_args(argv)
    try:
        run(args.db, args.raw_dir, args.regenerate, args.orders, args.customers, args.seed, args.skip_dq)
    except quality.DataQualityError as exc:
        log.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
