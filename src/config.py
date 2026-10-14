"""Central configuration: paths and defaults."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = ROOT / "data" / "raw"
WAREHOUSE_DIR = ROOT / "warehouse"
DB_PATH = WAREHOUSE_DIR / "warehouse.duckdb"
SQL_DIR = ROOT / "sql"
SEEDS_DIR = ROOT / "seeds"

DEFAULT_ORDERS = 40_000
DEFAULT_CUSTOMERS = 5_000
DEFAULT_SEED = 42

# Raw files the generator produces and the ingestion step loads into `bronze`.
RAW_TABLES = ["customers", "products", "orders", "order_items", "deliveries"]
