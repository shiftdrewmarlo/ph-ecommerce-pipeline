"""Generate a deliberately messy synthetic Philippine e-commerce dataset.

The data mimics what you'd get from an online store's operational exports:
inconsistent casing, mixed date formats, duplicate rows, orphan foreign keys,
impossible values. The pipeline's job is to clean it and say what it dropped.

Run:  python -m src.generate_data --orders 40000 --seed 42
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

log = logging.getLogger(__name__)

FIRST_NAMES = [
    "Juan", "Maria", "Jose", "Ana", "Mark", "Angelica", "John", "Kristine", "Paolo",
    "Bea", "Carlo", "Jasmine", "Miguel", "Patricia", "Rafael", "Nicole", "Gabriel",
    "Andrea", "Joshua", "Camille", "Daniel", "Trisha", "Francis", "Jessa", "Kevin",
]
LAST_NAMES = [
    "Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Garcia", "Mendoza", "Torres",
    "Villanueva", "Ramos", "Aquino", "Castillo", "Flores", "Dela Cruz", "Navarro",
    "Domingo", "Salazar", "Pascual", "Valdez", "Manalo",
]

# category -> list of (product name, base price in PHP)
CATALOG = {
    "Electronics": [("Wireless Earbuds", 1299), ("Power Bank 20000mAh", 1599), ("Bluetooth Speaker", 1899),
                    ("USB-C Cable 2m", 249), ("Smartwatch", 2999), ("Phone Case", 199),
                    ("Webcam 1080p", 1499), ("Mechanical Keyboard", 2499)],
    "Beauty": [("Sunscreen SPF50", 399), ("Lip Tint", 249), ("Facial Cleanser", 329),
               ("Serum Vitamin C", 599), ("Hair Mask", 289), ("Perfume 50ml", 899),
               ("Body Lotion", 259), ("Cushion Foundation", 749)],
    "Home & Living": [("LED Desk Lamp", 699), ("Storage Box Set", 549), ("Bed Sheet Queen", 999),
                      ("Electric Kettle", 849), ("Air Fryer 4L", 2799), ("Scented Candle", 299),
                      ("Wall Clock", 449), ("Dish Rack", 379)],
    "Fashion": [("Cotton T-Shirt", 299), ("Denim Jeans", 899), ("Sneakers", 1799),
                ("Tote Bag", 449), ("Hoodie", 799), ("Sandals", 349),
                ("Baseball Cap", 249), ("Dress Midi", 699)],
    "Grocery": [("Instant Coffee 30s", 189), ("Canned Tuna 6pk", 329), ("Rice 5kg", 299),
                ("Cooking Oil 1L", 119), ("Corned Beef 3pk", 249), ("Chocolate Box", 199),
                ("Cereal 500g", 229), ("Noodles 12pk", 259)],
    "Sports": [("Yoga Mat", 599), ("Dumbbell Set 10kg", 1299), ("Resistance Bands", 349),
               ("Water Bottle 1L", 299), ("Jump Rope", 199), ("Running Shorts", 449)],
    "Toys": [("Building Blocks 500pc", 899), ("Plush Toy", 349), ("Board Game", 799),
             ("RC Car", 1199), ("Puzzle 1000pc", 549), ("Art Set", 399)],
}
CATEGORY_VARIANTS = {
    "Electronics": ["Electronics", "electronics", "ELECTRONICS"],
    "Beauty": ["Beauty", "beauty", "Beauty "],
    "Home & Living": ["Home & Living", "Home and Living", "home & living"],
    "Fashion": ["Fashion", "fashion", "FASHION"],
    "Grocery": ["Grocery", "grocery", "Grocery "],
    "Sports": ["Sports", "sports"],
    "Toys": ["Toys", "toys", "TOYS"],
}

STATUSES = ["delivered", "cancelled", "returned", "shipped", "pending", "failed"]
STATUS_P = [0.78, 0.08, 0.05, 0.04, 0.02, 0.03]
STATUS_VARIANTS = {
    "delivered": ["delivered", "Delivered", "DELIVERED", "completed"],
    "cancelled": ["cancelled", "Cancelled", "canceled", "CANCELLED"],
    "returned": ["returned", "Returned", "return"],
    "shipped": ["shipped", "Shipped", "in transit"],
    "pending": ["pending", "Pending"],
    "failed": ["failed", "Failed", "delivery failed"],
}

PAYMENTS = ["gcash", "cod", "maya", "credit card", "bank transfer", "grabpay"]
PAYMENT_P = [0.35, 0.30, 0.10, 0.12, 0.05, 0.08]
PAYMENT_VARIANTS = {
    "gcash": ["GCash", "gcash", "G-Cash"],
    "cod": ["COD", "cod", "Cash on Delivery"],
    "maya": ["Maya", "PayMaya", "maya"],
    "credit card": ["Credit Card", "credit_card", "CC"],
    "bank transfer": ["Bank Transfer", "bank"],
    "grabpay": ["GrabPay", "grabpay"],
}
COURIERS = {
    "J&T Express": ["J&T Express", "J&T", "JNT"],
    "LBC": ["LBC", "lbc"],
    "Flash Express": ["Flash Express", "Flash", "flash express"],
    "Ninja Van": ["Ninja Van", "NinjaVan", "ninja van"],
}
COURIER_P = [0.38, 0.17, 0.27, 0.18]
VOUCHERS = ["FREESHIP", "PAYDAY15", "NEWUSER", "SALE99", "BIGSALE"]

START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2026-09-30")


def _load_city_variants() -> dict[str, list[str]]:
    """City -> list of raw spellings. The seed CSV is the single source of truth."""
    seed = pd.read_csv(config.SEEDS_DIR / "city_mapping.csv")
    return seed.groupby("city")["raw_value"].apply(list).to_dict()


def _messy_case(rng: np.random.Generator, value: str) -> str:
    """Randomly vary casing/whitespace the way hand-typed data does."""
    r = rng.random()
    if r < 0.15:
        return value.upper()
    if r < 0.30:
        return value.title()
    if r < 0.35:
        return f" {value} "
    return value


def _pick(rng: np.random.Generator, options: list[str], n: int) -> np.ndarray:
    return rng.choice(options, size=n)


def _format_date(rng: np.random.Generator, dates: pd.Series) -> list[str]:
    """Render dates in a mix of formats: ISO (70%), US (20%), dd-Mon-yyyy (10%)."""
    fmts = rng.choice([0, 1, 2], size=len(dates), p=[0.70, 0.20, 0.10])
    out = []
    for d, f in zip(dates, fmts, strict=True):
        if f == 0:
            out.append(d.strftime("%Y-%m-%d"))
        elif f == 1:
            out.append(d.strftime("%m/%d/%Y"))
        else:
            out.append(d.strftime("%d-%b-%Y"))
    return out


def make_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    city_variants = _load_city_variants()
    cities = list(city_variants)
    # Metro Manila is over-represented, as in reality.
    weights = np.array([3.0 if "Metro Manila" in c or c in {"Quezon City", "Manila", "Makati", "Taguig", "Pasig",
                                                           "Mandaluyong", "Caloocan"} else 1.0 for c in cities])
    weights /= weights.sum()
    chosen = rng.choice(cities, size=n, p=weights)

    first = rng.choice(FIRST_NAMES, size=n)
    last = rng.choice(LAST_NAMES, size=n)
    ids = [f"C{i:06d}" for i in range(1, n + 1)]
    signup = START - pd.to_timedelta(rng.integers(0, 730, size=n), unit="D")
    updated = pd.Timestamp("2026-01-01") + pd.to_timedelta(rng.integers(0, 270, size=n), unit="D")

    emails = [f"{fn}.{ln}{i}@example.com".replace(" ", "").lower()
              for fn, ln, i in zip(first, last, range(n), strict=True)]
    phones = []
    for _ in range(n):
        core = f"9{rng.integers(100000000, 999999999)}"
        style = rng.choice(["intl", "local", "bare", "spaced", "none"], p=[0.35, 0.35, 0.10, 0.17, 0.03])
        if style == "intl":
            phones.append(f"+63{core}")
        elif style == "local":
            phones.append(f"0{core}")
        elif style == "bare":
            phones.append(core)
        elif style == "spaced":
            phones.append(f"+63 {core[:3]} {core[3:6]} {core[6:]}")
        else:
            phones.append("")

    df = pd.DataFrame({
        "customer_id": ids,
        "first_name": [_messy_case(rng, x) for x in first],
        "last_name": [_messy_case(rng, x) for x in last],
        "email": [e if rng.random() > 0.03 else "" for e in emails],
        "phone": phones,
        "city": [str(rng.choice(city_variants[c])) for c in chosen],
        "signup_date": [d.strftime("%Y-%m-%d") if rng.random() > 0.15 else d.strftime("%m/%d/%Y") for d in signup],
        "updated_at": updated.strftime("%Y-%m-%d %H:%M:%S"),
    })
    df["email"] = [e.upper() if rng.random() < 0.05 and e else e for e in df["email"]]

    # ~2% duplicated customers: an older, stale version of the same customer_id.
    dups = df.sample(frac=0.02, random_state=int(rng.integers(0, 1_000_000))).copy()
    dups["updated_at"] = (pd.to_datetime(dups["updated_at"]) - pd.Timedelta(days=90)).dt.strftime("%Y-%m-%d %H:%M:%S")
    dups["phone"] = ""
    return pd.concat([df, dups], ignore_index=True).sample(frac=1, random_state=1).reset_index(drop=True)


def make_products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    pid = 1
    for category, items in CATALOG.items():
        for name, price in items:
            jitter = round(price * rng.uniform(0.95, 1.10), 2)
            rows.append({
                "product_id": f"P{pid:04d}",
                "product_name": name,
                "category": str(rng.choice(CATEGORY_VARIANTS[category])),
                "unit_price": jitter,
            })
            pid += 1
    return pd.DataFrame(rows)


def make_orders(rng: np.random.Generator, n: int, customer_ids: list[str]) -> pd.DataFrame:
    days = (END - START).days
    # Seasonality: lift on double-digit sale days (9.9, 10.10, 11.11, 12.12) and paydays.
    all_days = pd.date_range(START, END, freq="D")
    w = np.ones(len(all_days))
    for i, d in enumerate(all_days):
        if d.day == d.month:
            w[i] *= 3.5
        if d.day in (15, 30):
            w[i] *= 1.6
        if d.month in (11, 12):
            w[i] *= 1.25
    w /= w.sum()
    order_dates = pd.Series(rng.choice(all_days, size=n, p=w))
    assert days > 0

    # Heavy-tail customer activity: a minority of customers place most orders.
    activity = rng.pareto(2.0, size=len(customer_ids)) + 1
    activity /= activity.sum()
    cust = rng.choice(customer_ids, size=n, p=activity)

    status_key = rng.choice(STATUSES, size=n, p=STATUS_P)
    pay_key = rng.choice(PAYMENTS, size=n, p=PAYMENT_P)
    # COD orders cancel / fail more often (a real PH e-commerce pain point).
    cod = pay_key == "cod"
    flip = cod & (status_key == "delivered") & (rng.random(n) < 0.10)
    status_key = np.where(flip, "cancelled", status_key)

    df = pd.DataFrame({
        "order_id": [f"O{i:07d}" for i in range(1, n + 1)],
        "customer_id": cust,
        "order_date": _format_date(rng, order_dates),
        "status": [str(rng.choice(STATUS_VARIANTS[s])) for s in status_key],
        "payment_method": [str(rng.choice(PAYMENT_VARIANTS[p])) for p in pay_key],
        "voucher_code": [str(rng.choice(VOUCHERS)) if rng.random() < 0.25 else "" for _ in range(n)],
        "shipping_fee": rng.choice([0, 49, 79, 99, 149], size=n, p=[0.25, 0.2, 0.25, 0.2, 0.1]),
    })

    # Anomalies
    orphan = rng.choice(n, size=max(1, int(n * 0.005)), replace=False)
    df.loc[orphan, "customer_id"] = [f"C9{i:05d}" for i in range(len(orphan))]
    future = rng.choice(n, size=max(1, int(n * 0.003)), replace=False)
    df.loc[future, "order_date"] = "2031-01-15"
    dupes = df.sample(frac=0.01, random_state=int(rng.integers(0, 1_000_000)))
    return pd.concat([df, dupes], ignore_index=True).sample(frac=1, random_state=2).reset_index(drop=True)


def make_order_items(rng: np.random.Generator, orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    order_ids = orders["order_id"].drop_duplicates().to_numpy()
    n_items = rng.choice([1, 2, 3, 4], size=len(order_ids), p=[0.50, 0.30, 0.15, 0.05])
    prod_ids = products["product_id"].to_numpy()
    prices = dict(zip(products["product_id"], products["unit_price"], strict=True))
    # Mildly skewed product popularity.
    pop = rng.pareto(1.5, size=len(prod_ids)) + 1
    pop /= pop.sum()

    rows = []
    item_no = 1
    for oid, k in zip(order_ids, n_items, strict=True):
        chosen = rng.choice(prod_ids, size=k, replace=False, p=pop)
        for pid in chosen:
            qty = int(rng.choice([1, 2, 3, 4, 5], p=[0.62, 0.22, 0.09, 0.05, 0.02]))
            rows.append((f"OI{item_no:08d}", oid, pid, qty, prices[pid]))
            item_no += 1
    df = pd.DataFrame(rows, columns=["order_item_id", "order_id", "product_id", "quantity", "unit_price"])

    bad_q = rng.choice(len(df), size=int(len(df) * 0.004), replace=False)
    df["quantity"] = df["quantity"].astype("object")
    df.loc[bad_q[: len(bad_q) // 2], "quantity"] = 0
    df.loc[bad_q[len(bad_q) // 2:], "quantity"] = ""
    orphan_p = rng.choice(len(df), size=max(1, int(len(df) * 0.002)), replace=False)
    df.loc[orphan_p, "product_id"] = "P9999"
    neg_price = rng.choice(len(df), size=max(1, int(len(df) * 0.002)), replace=False)
    df.loc[neg_price, "unit_price"] = -1
    return df


def make_deliveries(rng: np.random.Generator, orders: pd.DataFrame) -> pd.DataFrame:
    base = orders.drop_duplicates("order_id").copy()
    norm = base["status"].str.strip().str.lower()
    shipped_statuses = {"delivered", "completed", "returned", "return", "shipped", "in transit", "failed",
                        "delivery failed"}
    base = base[norm.isin(shipped_statuses)].copy()
    base["_status"] = norm[base.index]

    parsed = pd.to_datetime(base["order_date"], format="mixed", errors="coerce")
    base = base[parsed.notna()].copy()
    parsed = parsed[base.index]
    n = len(base)

    ship_lag = rng.integers(0, 3, size=n)
    transit = rng.choice([1, 2, 3, 4, 5, 6, 8, 10], size=n, p=[0.12, 0.25, 0.22, 0.15, 0.10, 0.08, 0.05, 0.03])
    courier_keys = rng.choice(list(COURIERS), size=n, p=COURIER_P)
    # Province-bound shipments are slower; "Ninja Van" is a bit slower here, "Flash" a bit faster.
    transit = transit + np.where(courier_keys == "Ninja Van", 1, 0) - np.where(courier_keys == "Flash Express", 1, 0)
    transit = np.clip(transit, 1, None)

    shipped = parsed + pd.to_timedelta(ship_lag, unit="D")
    delivered = shipped + pd.to_timedelta(transit, unit="D")
    is_delivered = base["_status"].isin(["delivered", "completed", "returned", "return"]).to_numpy()

    df = pd.DataFrame({
        "order_id": base["order_id"].to_numpy(),
        "courier": [str(rng.choice(COURIERS[c])) for c in courier_keys],
        "shipped_date": shipped.dt.strftime("%Y-%m-%d").to_numpy(),
        "delivered_date": np.where(is_delivered, delivered.dt.strftime("%Y-%m-%d"), ""),
    })
    # Anomaly: delivered before shipped.
    anomalies = df[df["delivered_date"] != ""].sample(frac=0.005, random_state=int(rng.integers(0, 1_000_000))).index
    df.loc[anomalies, "delivered_date"] = (
        pd.to_datetime(df.loc[anomalies, "shipped_date"]) - pd.Timedelta(days=2)
    ).dt.strftime("%Y-%m-%d")
    return df


def generate(out_dir: Path, n_orders: int, n_customers: int, seed: int) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    customers = make_customers(rng, n_customers)
    products = make_products(rng)
    orders = make_orders(rng, n_orders, customers["customer_id"].drop_duplicates().tolist())
    items = make_order_items(rng, orders, products)
    deliveries = make_deliveries(rng, orders)

    frames = {"customers": customers, "products": products, "orders": orders,
              "order_items": items, "deliveries": deliveries}
    counts = {}
    for name, frame in frames.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
        counts[name] = len(frame)
        log.info("wrote %-12s %8d rows", name, len(frame))
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--orders", type=int, default=config.DEFAULT_ORDERS)
    p.add_argument("--customers", type=int, default=config.DEFAULT_CUSTOMERS)
    p.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    p.add_argument("--out", type=Path, default=config.RAW_DIR)
    args = p.parse_args()
    generate(args.out, args.orders, args.customers, args.seed)


if __name__ == "__main__":
    main()
