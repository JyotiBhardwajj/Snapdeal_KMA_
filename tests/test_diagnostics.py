"""The analytics must be exact: Disha only ever quotes numbers produced here."""

import pytest

from app import diagnostics
from app.formatting import format_inr, pct_change, spoken_inr
from app.seller_data import SELLER, brief_metrics_table


def test_brief_metrics_are_exactly_the_assignment_data():
    lm, tm = SELLER.last_month, SELLER.this_month
    assert (lm.sales_inr, lm.orders, lm.cancellation_rate, lm.avg_selling_price_inr, lm.out_of_stock_products) == (
        200_000,
        400,
        0.08,
        500,
        5,
    )
    assert (tm.sales_inr, tm.orders, tm.cancellation_rate, tm.avg_selling_price_inr, tm.out_of_stock_products) == (
        135_000,
        270,
        0.14,
        500,
        18,
    )
    assert [row["metric"] for row in brief_metrics_table()] == [
        "Sales",
        "Orders",
        "Cancellation rate",
        "Average selling price",
        "Out-of-stock products",
    ]


def test_assumed_sku_data_reconciles_with_brief_totals():
    tail = SELLER.long_tail
    lm_orders = (
        sum(s.last_month_orders for s in SELLER.top_skus)
        + tail.newly_oos_last_month_orders
        + tail.in_stock_last_month_orders
    )
    tm_orders = (
        sum(s.this_month_orders for s in SELLER.top_skus)
        + tail.newly_oos_this_month_orders
        + tail.in_stock_this_month_orders
    )
    assert lm_orders == SELLER.last_month.orders
    assert tm_orders == SELLER.this_month.orders

    top_oos_now = sum(1 for s in SELLER.top_skus if s.is_out_of_stock)
    assert (
        top_oos_now + tail.newly_out_of_stock_skus + tail.chronic_out_of_stock_skus
        == SELLER.this_month.out_of_stock_products
    )
    assert tail.chronic_out_of_stock_skus == SELLER.last_month.out_of_stock_products
    assert len(SELLER.top_skus) + tail.sku_count == SELLER.active_listings
    assert tail.newly_out_of_stock_skus + tail.chronic_out_of_stock_skus + tail.in_stock_skus == tail.sku_count


def test_assumed_cancellations_match_brief_rates():
    assert SELLER.cancellations_last_month.total == round(
        SELLER.last_month.orders * SELLER.last_month.cancellation_rate
    )
    assert SELLER.cancellations_this_month.total == round(
        SELLER.this_month.orders * SELLER.this_month.cancellation_rate
    )


def test_sales_change_is_all_volume_no_price():
    m = diagnostics.headline_metrics()
    assert m["sales_change"] == -65_000
    assert m["sales_change_pct"] == -32.5
    assert m["volume_effect"] == -65_000
    assert m["price_effect"] == 0
    assert m["volume_effect"] + m["price_effect"] == m["sales_change"]


def test_realised_sales_after_cancellations():
    m = diagnostics.headline_metrics()
    assert m["realised_sales_last_month"] == 184_000  # 400 * 92% * 500
    assert m["realised_sales_this_month"] == 116_100  # 270 * 86% * 500
    assert m["excess_cancellation_cost"] == 8_100  # 270 * 6pp * 500


def test_order_attribution_splits_the_whole_drop():
    a = diagnostics.order_attribution()
    assert a["lost_orders_out_of_stock"] == 112
    assert a["lost_orders_in_stock"] == 18
    assert a["lost_orders_out_of_stock"] + a["lost_orders_in_stock"] == a["total_lost_orders"] == 130


def test_sales_bridge_walks_from_last_to_this_month():
    bridge = diagnostics.sales_bridge()
    assert bridge[0]["value"] + sum(s["value"] for s in bridge[1:-1]) == bridge[-1]["value"]
    assert bridge[1]["value"] == -56_000 and bridge[2]["value"] == -9_000


def test_verdicts():
    analysis = diagnostics.analyze_sales_drop()
    verdicts = {d["key"]: d["verdict"] for d in analysis["drivers"]}
    assert verdicts == {
        "stock": diagnostics.PRIMARY,
        "cancellations": diagnostics.CONTRIBUTING,
        "visibility": diagnostics.KNOCK_ON,
        "pricing": diagnostics.RULED_OUT,
    }
    assert analysis["out_of_stock_bestsellers"][0].startswith("Steel Water Bottle")
    assert "32.5 percent" in analysis["spoken_numbers"]["sales_change"]


def test_running_low_flags_items_with_under_two_weeks_of_cover():
    low = diagnostics.analyze_sales_drop()["running_low"]
    assert [item["name"] for item in low] == ["Ceramic Coffee Mugs (set of 4)"]
    assert low[0]["days_of_cover"] == pytest.approx(8.6)


def test_candidate_actions_are_ranked_and_quantified():
    actions = diagnostics.candidate_actions()
    assert [a["rank"] for a in actions] == sorted(a["rank"] for a in actions)
    assert "₹56,000" in actions[0]["expected_impact"]
    assert "₹8,100" in actions[1]["expected_impact"]


@pytest.mark.parametrize("area", diagnostics.DETAIL_AREAS)
def test_account_details_areas(area):
    assert diagnostics.account_details(area)


def test_account_details_unknown_area():
    with pytest.raises(ValueError):
        diagnostics.account_details("weather")


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (135_000, "₹1,35,000"),
        (200_000, "₹2,00,000"),
        (8_100, "₹8,100"),
        (-65_000, "-₹65,000"),
        (500, "₹500"),
        (12_345_678, "₹1,23,45,678"),
    ],
)
def test_format_inr(amount, text):
    assert format_inr(amount) == text


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (135_000, "1.35 lakh rupees"),
        (200_000, "2 lakh rupees"),
        (56_000, "56 thousand rupees"),
        (8_100, "8,100 rupees"),
    ],
)
def test_spoken_inr(amount, text):
    assert spoken_inr(amount) == text


def test_pct_change():
    assert pct_change(400, 270) == -32.5
    assert pct_change(0, 10) == 0.0
