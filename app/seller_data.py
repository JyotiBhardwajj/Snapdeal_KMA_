"""Mock seller account used by the Virtual KAM.

The data has two clearly separated layers:

1. ``BRIEF`` metrics — copied *exactly* from the Snapdeal assignment brief.
2. ``ASSUMED`` details — reasonable, clearly-labelled assumptions that make the
   conversation specific (SKU-level stock, cancellation reasons, traffic, an
   upcoming sale). They are constructed so that they reconcile exactly with the
   brief's totals (orders, out-of-stock count, cancellation counts); unit tests
   enforce this.

No real Snapdeal data, systems or credentials are used anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonthMetrics:
    """One month of headline metrics, exactly as given in the brief."""

    sales_inr: int
    orders: int
    cancellation_rate: float  # 0.08 == 8%
    avg_selling_price_inr: int
    out_of_stock_products: int


@dataclass(frozen=True)
class Sku:
    """A top-selling product (ASSUMED)."""

    sku_id: str
    name: str
    last_month_orders: int
    this_month_orders: int
    current_stock: int
    days_out_of_stock: int  # days out of stock in the current 30-day month
    price_index: float  # our price / lowest comparable competitor price (1.00 = parity)
    spoken: str = ""  # how to say a quantity of it, e.g. "62 water bottle packs"

    @property
    def is_out_of_stock(self) -> bool:
        return self.current_stock == 0

    @property
    def orders_lost(self) -> int:
        return self.last_month_orders - self.this_month_orders

    @property
    def days_of_cover(self) -> float | None:
        """Days until stock runs out at this month's sales rate."""
        if self.is_out_of_stock or self.this_month_orders == 0:
            return None
        return round(self.current_stock / (self.this_month_orders / 30), 1)


@dataclass(frozen=True)
class LongTail:
    """The remaining catalogue, aggregated (ASSUMED)."""

    sku_count: int
    newly_out_of_stock_skus: int
    newly_oos_last_month_orders: int
    newly_oos_this_month_orders: int
    chronic_out_of_stock_skus: int  # already out of stock last month and still out
    in_stock_skus: int
    in_stock_last_month_orders: int
    in_stock_this_month_orders: int


@dataclass(frozen=True)
class CancellationReasons:
    """Cancelled-order counts by reason (ASSUMED)."""

    out_of_stock: int  # seller cancelled: item not physically available
    late_dispatch: int  # auto-cancelled: not shipped within SLA
    customer_initiated: int

    @property
    def total(self) -> int:
        return self.out_of_stock + self.late_dispatch + self.customer_initiated


@dataclass(frozen=True)
class SaleEvent:
    """An upcoming promotional opportunity (FICTIONAL, for the demo)."""

    name: str
    starts_in_days: int
    nomination_closes_in_days: int
    min_units: int
    expected_uplift: str

    @property
    def requirement(self) -> str:
        return f"At least {self.min_units} units in stock for each nominated product"


@dataclass(frozen=True)
class SellerAccount:
    seller_id: str
    seller_name: str
    business_name: str
    city: str
    category: str
    seller_since: int
    fulfilment: str
    active_listings: int

    last_month: MonthMetrics
    this_month: MonthMetrics

    top_skus: tuple[Sku, ...]
    long_tail: LongTail
    cancellations_last_month: CancellationReasons
    cancellations_this_month: CancellationReasons
    product_views_last_month: int
    product_views_this_month: int
    upcoming_event: SaleEvent

    assumptions: tuple[str, ...]


# --------------------------------------------------------------------------------------
# 1) Exactly the sample data from the assignment brief.
# --------------------------------------------------------------------------------------
BRIEF_LAST_MONTH = MonthMetrics(
    sales_inr=200_000,
    orders=400,
    cancellation_rate=0.08,
    avg_selling_price_inr=500,
    out_of_stock_products=5,
)
BRIEF_THIS_MONTH = MonthMetrics(
    sales_inr=135_000,
    orders=270,
    cancellation_rate=0.14,
    avg_selling_price_inr=500,
    out_of_stock_products=18,
)

# --------------------------------------------------------------------------------------
# 2) Assumptions (clearly labelled; reconcile with the brief's totals).
# --------------------------------------------------------------------------------------
ASSUMPTIONS: tuple[str, ...] = (
    "Seller profile (Gupta Home Essentials, Jaipur, Home & Kitchen, 60 active listings) is fictional.",
    "'Sales' and 'Orders' in the brief are gross (placed) values; cancellations reduce realised revenue.",
    "'Out-of-stock products' is the count of listings with zero stock at month end.",
    "SKU-level orders, stock and days out of stock for the top 8 products, plus an aggregated "
    "long tail of 52 products, sum exactly to the brief's 400 and 270 orders and 5 and 18 stock-outs.",
    "Cancellation reasons (32 last month, 38 this month) match the brief's 8% and 14% rates.",
    "Product page views: 20,000 last month and 15,400 this month.",
    "Competitor prices: top products are priced within ±3% of the lowest comparable listing.",
    "Marketplace mechanics: out-of-stock listings drop out of search, and high seller-side "
    "cancellations reduce search ranking.",
    "'Savings Week' sale event (nominations close in 9 days) is fictional, for the demo.",
    "Restock planning: unit cost ₹300 (60% of the ₹500 average selling price); orders cover 30 days of demand; "
    "reorder point = daily demand x (supplier lead time + 7 safety days); default lead time 7 days.",
    "The 7-day follow-up call uses simulated week-later metrics, driven by which actions were agreed on the first "
    "call.",
)

SELLER = SellerAccount(
    seller_id="SD-JPR-20417",
    seller_name="Rajesh Gupta",
    business_name="Gupta Home Essentials",
    city="Jaipur, Rajasthan",
    category="Home & Kitchen",
    seller_since=2021,
    fulfilment="Seller-fulfilled (ships from own warehouse)",
    active_listings=60,
    last_month=BRIEF_LAST_MONTH,
    this_month=BRIEF_THIS_MONTH,
    top_skus=(
        Sku("GHE-101", "Steel Water Bottle 1L (pack of 2)", 62, 20, 0, 20, 1.02, "water bottle packs"),
        Sku("GHE-102", "Cotton Kitchen Towels (set of 6)", 48, 17, 0, 19, 0.98, "kitchen towel sets"),
        Sku("GHE-103", "Airtight Glass Jars (set of 3)", 41, 22, 0, 14, 1.01, "glass jar sets"),
        Sku("GHE-104", "Non-stick Tawa 28 cm", 38, 33, 46, 0, 0.99, "tawas"),
        Sku("GHE-105", "Steel Lunch Box (3-tier)", 33, 26, 31, 0, 1.03, "lunch boxes"),
        Sku("GHE-106", "Microfiber Cleaning Cloths (pack of 5)", 30, 26, 120, 0, 0.97, "cleaning cloth packs"),
        Sku("GHE-107", "Wooden Spice Rack Organiser", 26, 14, 0, 12, 1.00, "spice racks"),
        Sku("GHE-108", "Ceramic Coffee Mugs (set of 4)", 24, 21, 6, 0, 1.02, "coffee mug sets"),
    ),
    long_tail=LongTail(
        sku_count=52,
        newly_out_of_stock_skus=9,
        newly_oos_last_month_orders=14,
        newly_oos_this_month_orders=6,
        chronic_out_of_stock_skus=5,
        in_stock_skus=38,
        in_stock_last_month_orders=84,
        in_stock_this_month_orders=85,
    ),
    cancellations_last_month=CancellationReasons(out_of_stock=9, late_dispatch=7, customer_initiated=16),
    cancellations_this_month=CancellationReasons(out_of_stock=24, late_dispatch=5, customer_initiated=9),
    product_views_last_month=20_000,
    product_views_this_month=15_400,
    upcoming_event=SaleEvent(
        name="Snapdeal Savings Week",
        starts_in_days=14,
        nomination_closes_in_days=9,
        min_units=20,
        expected_uplift="Featured products typically see 2-3x daily orders during the event (assumption)",
    ),
    assumptions=ASSUMPTIONS,
)


def brief_metrics_table(account: SellerAccount = SELLER) -> list[dict]:
    """The brief's sample data as rows for the UI."""
    lm, tm = account.last_month, account.this_month
    return [
        {"metric": "Sales", "last_month": lm.sales_inr, "this_month": tm.sales_inr, "unit": "inr"},
        {"metric": "Orders", "last_month": lm.orders, "this_month": tm.orders, "unit": "count"},
        {
            "metric": "Cancellation rate",
            "last_month": lm.cancellation_rate,
            "this_month": tm.cancellation_rate,
            "unit": "ratio",
            "higher_is_worse": True,
        },
        {
            "metric": "Average selling price",
            "last_month": lm.avg_selling_price_inr,
            "this_month": tm.avg_selling_price_inr,
            "unit": "inr",
        },
        {
            "metric": "Out-of-stock products",
            "last_month": lm.out_of_stock_products,
            "this_month": tm.out_of_stock_products,
            "unit": "count",
            "higher_is_worse": True,
        },
    ]


def public_profile(account: SellerAccount = SELLER) -> dict:
    return {
        "seller_id": account.seller_id,
        "seller_name": account.seller_name,
        "business_name": account.business_name,
        "city": account.city,
        "category": account.category,
        "seller_since": account.seller_since,
        "fulfilment": account.fulfilment,
        "active_listings": account.active_listings,
    }
