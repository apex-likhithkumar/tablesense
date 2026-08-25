"""Generate the four demo files. Fixed seed, so expected eval answers never drift."""

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 20260826
OUT = Path(__file__).parent / "samples"

REGIONS = ["North", "South", "East", "West"]
CATEGORIES = ["Bridal Wear", "Casual Wear", "Accessories", "Footwear"]
SEGMENTS = ["New", "Repeat", "VIP"]
CITIES = ["Hyderabad", "Chennai", "Mumbai", "Delhi", "Bengaluru", "Pune"]
RETURN_REASONS = ["Size issue", "Damaged", "Not as described", "Changed mind"]


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    products = []
    for i in range(1, 41):
        category = CATEGORIES[i % len(CATEGORIES)]
        products.append(
            {
                "product_id": f"P{i:03d}",
                "product_name": f"{category.split()[0]} Item {i:03d}",
                "category": category,
                "cost_price": round(rng.uniform(400, 6000), 2),
            }
        )
    products_df = pd.DataFrame(products)

    customers = []
    for i in range(1, 121):
        customers.append(
            {
                "customer_id": f"C{i:04d}",
                "customer_name": f"Customer {i:04d}",
                "city": rng.choice(CITIES),
                "segment": rng.choices(SEGMENTS, weights=[5, 3, 2])[0],
                "signup_date": date(2024, 1, 1) + timedelta(days=rng.randint(0, 700)),
            }
        )
    customers_df = pd.DataFrame(customers)

    start = date(2025, 1, 1)
    orders = []
    for i in range(1, 1501):
        product = rng.choice(products)
        unit_price = round(product["cost_price"] * rng.uniform(1.25, 2.1), 2)
        orders.append(
            {
                "order_id": f"O{i:05d}",
                "customer_id": f"C{rng.randint(1, 120):04d}",
                "product_id": product["product_id"],
                "order_date": start + timedelta(days=rng.randint(0, 545)),
                "quantity": rng.randint(1, 4),
                "unit_price": unit_price,
                "region": rng.choice(REGIONS),
            }
        )
    orders_df = pd.DataFrame(orders)

    returns = []
    for i, order in enumerate(rng.sample(orders, k=120), start=1):
        returns.append(
            {
                "return_id": f"R{i:04d}",
                "order_id": order["order_id"],
                "return_date": order["order_date"] + timedelta(days=rng.randint(1, 21)),
                "reason": rng.choice(RETURN_REASONS),
            }
        )
    returns_df = pd.DataFrame(returns)

    orders_df.to_csv(OUT / "orders.csv", index=False)
    products_df.to_csv(OUT / "products.csv", index=False)
    returns_df.to_csv(OUT / "returns.csv", index=False)
    customers_df.to_excel(OUT / "customers.xlsx", index=False)

    print(f"orders     {len(orders_df):>5}")
    print(f"customers  {len(customers_df):>5}")
    print(f"products   {len(products_df):>5}")
    print(f"returns    {len(returns_df):>5}")


if __name__ == "__main__":
    main()
