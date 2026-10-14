from __future__ import annotations

import pandas as pd

from src import config, generate_data


def test_city_mapping_seed_is_clean():
    seed = pd.read_csv(config.SEEDS_DIR / "city_mapping.csv")
    assert seed["raw_value"].is_unique, "raw_value must be unique or the silver join will fan out rows"
    assert (seed["raw_value"] == seed["raw_value"].str.strip().str.lower()).all(), "raw_value must be lowercase/trimmed"
    assert seed[["city", "province", "region"]].notna().all().all()


def test_generator_is_deterministic(tmp_path):
    generate_data.generate(tmp_path / "a", n_orders=500, n_customers=80, seed=1)
    generate_data.generate(tmp_path / "b", n_orders=500, n_customers=80, seed=1)
    for table in config.RAW_TABLES:
        assert (tmp_path / "a" / f"{table}.csv").read_bytes() == (tmp_path / "b" / f"{table}.csv").read_bytes()


def test_generator_different_seed_differs(tmp_path):
    generate_data.generate(tmp_path / "a", n_orders=500, n_customers=80, seed=1)
    generate_data.generate(tmp_path / "b", n_orders=500, n_customers=80, seed=2)
    assert (tmp_path / "a" / "orders.csv").read_bytes() != (tmp_path / "b" / "orders.csv").read_bytes()


def test_generator_injects_the_mess_the_pipeline_must_handle(tmp_path):
    generate_data.generate(tmp_path, n_orders=2_000, n_customers=200, seed=3)
    orders = pd.read_csv(tmp_path / "orders.csv", dtype=str, keep_default_na=False)
    customers = pd.read_csv(tmp_path / "customers.csv", dtype=str, keep_default_na=False)

    assert orders["order_id"].duplicated().any(), "expected duplicate order rows"
    assert customers["customer_id"].duplicated().any(), "expected duplicate customer rows"
    assert orders["status"].nunique() > 6, "expected inconsistent status spellings"
    assert orders["order_date"].str.contains("/").any(), "expected US-style dates"
    assert (~orders["customer_id"].isin(customers["customer_id"])).any(), "expected orphan customer ids"
