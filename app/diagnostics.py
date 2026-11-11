"""Deterministic diagnostics engine.

Design principle: *the LLM handles the conversation, code handles the math.*
Every number Disha says comes from these functions, so the voice agent cannot
hallucinate figures, and the analysis is unit-testable and explainable.

The engine:
  1. decomposes the sales change into price vs. volume effects,
  2. attributes lost orders to stock-outs vs. in-stock products (SKU level),
  3. sizes the rupee impact of each driver,
  4. gives each hypothesis (stock, cancellations, visibility, pricing) a verdict,
  5. proposes data-driven questions and ranked candidate actions.
"""

from __future__ import annotations

from typing import Any

from app.formatting import format_inr, pct_change, spoken_inr
from app.seller_data import SELLER, SellerAccount, Sku

# Verdict labels shared with the UI.
PRIMARY = "primary_driver"
CONTRIBUTING = "contributing"
KNOCK_ON = "knock_on_effect"
RULED_OUT = "ruled_out"

AT_RISK_DAYS_OF_COVER = 14  # flag in-stock items that will run out within two weeks
COMPETITIVE_PRICE_BAND = 0.05  # within ±5% of the lowest competitor counts as competitive


def _newly_out_of_stock(account: SellerAccount) -> list[Sku]:
    skus = [s for s in account.top_skus if s.is_out_of_stock and s.days_out_of_stock > 0]
    return sorted(skus, key=lambda s: s.orders_lost, reverse=True)


def _in_stock(account: SellerAccount) -> list[Sku]:
    return [s for s in account.top_skus if not s.is_out_of_stock]


def running_low(account: SellerAccount = SELLER) -> list[Sku]:
    """In-stock products that will run out within two weeks at the current sales rate."""
    return _at_risk(account)


def _at_risk(account: SellerAccount) -> list[Sku]:
    return [s for s in _in_stock(account) if s.days_of_cover is not None and s.days_of_cover < AT_RISK_DAYS_OF_COVER]


def order_attribution(account: SellerAccount = SELLER) -> dict[str, int]:
    """Split the change in orders between stock-outs and in-stock products."""
    tail = account.long_tail
    lost_top_oos = sum(s.orders_lost for s in _newly_out_of_stock(account))
    lost_tail_oos = tail.newly_oos_last_month_orders - tail.newly_oos_this_month_orders
    lost_in_stock = sum(s.orders_lost for s in _in_stock(account)) + (
        tail.in_stock_last_month_orders - tail.in_stock_this_month_orders
    )
    return {
        "lost_orders_top_oos": lost_top_oos,
        "lost_orders_tail_oos": lost_tail_oos,
        "lost_orders_out_of_stock": lost_top_oos + lost_tail_oos,
        "lost_orders_in_stock": lost_in_stock,
        "total_lost_orders": account.last_month.orders - account.this_month.orders,
    }


def headline_metrics(account: SellerAccount = SELLER) -> dict[str, Any]:
    lm, tm = account.last_month, account.this_month
    cancelled_lm = round(lm.orders * lm.cancellation_rate)
    cancelled_tm = round(tm.orders * tm.cancellation_rate)
    realised_lm = round(lm.orders * (1 - lm.cancellation_rate) * lm.avg_selling_price_inr)
    realised_tm = round(tm.orders * (1 - tm.cancellation_rate) * tm.avg_selling_price_inr)
    return {
        "sales_last_month": lm.sales_inr,
        "sales_this_month": tm.sales_inr,
        "sales_change": tm.sales_inr - lm.sales_inr,
        "sales_change_pct": pct_change(lm.sales_inr, tm.sales_inr),
        "orders_last_month": lm.orders,
        "orders_this_month": tm.orders,
        "orders_change": tm.orders - lm.orders,
        "orders_change_pct": pct_change(lm.orders, tm.orders),
        "asp_last_month": lm.avg_selling_price_inr,
        "asp_this_month": tm.avg_selling_price_inr,
        # Additive price/volume decomposition of the sales change.
        "volume_effect": (tm.orders - lm.orders) * lm.avg_selling_price_inr,
        "price_effect": (tm.avg_selling_price_inr - lm.avg_selling_price_inr) * tm.orders,
        "cancellation_rate_last_month_pct": round(lm.cancellation_rate * 100, 1),
        "cancellation_rate_this_month_pct": round(tm.cancellation_rate * 100, 1),
        "cancelled_orders_last_month": cancelled_lm,
        "cancelled_orders_this_month": cancelled_tm,
        "realised_sales_last_month": realised_lm,
        "realised_sales_this_month": realised_tm,
        "realised_sales_change_pct": pct_change(realised_lm, realised_tm),
        "excess_cancellation_cost": round(
            tm.orders * (tm.cancellation_rate - lm.cancellation_rate) * tm.avg_selling_price_inr
        ),
        "out_of_stock_last_month": lm.out_of_stock_products,
        "out_of_stock_this_month": tm.out_of_stock_products,
        "out_of_stock_share_pct": round(tm.out_of_stock_products / account.active_listings * 100),
        "active_listings": account.active_listings,
    }


def sales_bridge(account: SellerAccount = SELLER) -> list[dict[str, Any]]:
    """Waterfall from last month's sales to this month's, by driver."""
    asp = account.last_month.avg_selling_price_inr
    attribution = order_attribution(account)
    m = headline_metrics(account)
    return [
        {"label": "Last month", "value": m["sales_last_month"], "kind": "total"},
        {
            "label": "Lost on out-of-stock products",
            "value": -attribution["lost_orders_out_of_stock"] * asp,
            "kind": "delta",
        },
        {
            "label": "Fewer orders on in-stock products",
            "value": -attribution["lost_orders_in_stock"] * asp,
            "kind": "delta",
        },
        {"label": "Price change", "value": m["price_effect"], "kind": "delta"},
        {"label": "This month", "value": m["sales_this_month"], "kind": "total"},
    ]


def analyze_sales_drop(account: SellerAccount = SELLER) -> dict[str, Any]:
    """Full diagnosis returned to the voice agent (and rendered in the UI)."""
    m = headline_metrics(account)
    attribution = order_attribution(account)
    asp = account.last_month.avg_selling_price_inr
    newly_oos = _newly_out_of_stock(account)
    at_risk = _at_risk(account)
    canc_lm, canc_tm = account.cancellations_last_month, account.cancellations_this_month
    views_change = pct_change(account.product_views_last_month, account.product_views_this_month)
    conv_lm = round(account.last_month.orders / account.product_views_last_month * 100, 2)
    conv_tm = round(account.this_month.orders / account.product_views_this_month * 100, 2)
    price_indices = [s.price_index for s in account.top_skus]
    pricing_competitive = all(abs(p - 1) <= COMPETITIVE_PRICE_BAND for p in price_indices)

    oos_value = attribution["lost_orders_out_of_stock"] * asp
    in_stock_value = attribution["lost_orders_in_stock"] * asp
    oos_share_of_drop = round(attribution["lost_orders_out_of_stock"] / attribution["total_lost_orders"] * 100)
    bestseller_names = [s.name for s in newly_oos]
    top_oos_lost = attribution["lost_orders_top_oos"]

    drivers = [
        {
            "key": "stock",
            "label": "Stock-outs",
            "verdict": PRIMARY,
            "headline": f"Stock-outs explain about {oos_share_of_drop}% of the drop",
            "evidence": [
                f"Out-of-stock products rose from {m['out_of_stock_last_month']} to "
                f"{m['out_of_stock_this_month']} ({m['out_of_stock_share_pct']}% of {m['active_listings']} listings)",
                f"{len(newly_oos)} of the top 8 bestsellers ran out for "
                f"{min(s.days_out_of_stock for s in newly_oos)}-{max(s.days_out_of_stock for s in newly_oos)} days "
                f"and lost {top_oos_lost} orders",
                f"In total ~{attribution['lost_orders_out_of_stock']} orders (~{format_inr(oos_value)}) "
                "were lost on products that went out of stock",
            ],
            "monthly_impact_inr": oos_value,
        },
        {
            "key": "cancellations",
            "label": "Cancellations",
            "verdict": CONTRIBUTING,
            "headline": (
                f"Cancellation rate up from {m['cancellation_rate_last_month_pct']:g}% to "
                f"{m['cancellation_rate_this_month_pct']:g}%, mostly stock-related"
            ),
            "evidence": [
                f"Cancelled orders went from {canc_lm.total} to {canc_tm.total} even though orders fell",
                f"Seller cancellations because the item was unavailable: {canc_lm.out_of_stock} → "
                f"{canc_tm.out_of_stock} ({round(canc_tm.out_of_stock / canc_tm.total * 100)}% of all cancellations)",
                f"Realised sales after cancellations fell {format_inr(m['realised_sales_last_month'])} → "
                f"{format_inr(m['realised_sales_this_month'])} ({m['realised_sales_change_pct']:g}%)",
            ],
            "monthly_impact_inr": m["excess_cancellation_cost"],
        },
        {
            "key": "visibility",
            "label": "Visibility",
            "verdict": KNOCK_ON,
            "headline": f"Product views down {abs(views_change):g}%: a knock-on effect",
            "evidence": [
                f"Product views {account.product_views_last_month:,} → {account.product_views_this_month:,}; "
                f"conversion {conv_lm:g}% → {conv_tm:g}%",
                "Out-of-stock listings drop out of search, and high seller cancellations lower ranking",
                f"Even in-stock products lost {attribution['lost_orders_in_stock']} orders "
                f"(~{format_inr(in_stock_value)})",
            ],
            "monthly_impact_inr": in_stock_value,
        },
        {
            "key": "pricing",
            "label": "Pricing",
            "verdict": RULED_OUT if pricing_competitive else CONTRIBUTING,
            "headline": "Pricing is not the problem" if pricing_competitive else "Some products are overpriced",
            "evidence": [
                f"Average selling price unchanged at {format_inr(m['asp_this_month'])}, so the price effect is "
                f"{format_inr(m['price_effect'])}; the whole drop is fewer orders",
                f"Top products are priced within {min(price_indices):.2f}-{max(price_indices):.2f}x of the "
                "lowest comparable competitor",
            ],
            "monthly_impact_inr": 0,
        },
    ]

    questions = [
        {
            "topic": "stock_and_supply",
            "question": "What caused the stock-outs this month: a supplier delay, cash flow, or a demand spike?",
        },
        {
            "topic": "inventory_process",
            "question": "How do you update stock on Snapdeal, manually or synced, and how often?",
        },
        {
            "topic": "cancellations",
            "question": (
                "Were most cancellations orders you couldn't fulfil because the item wasn't actually available?"
            ),
        },
        {
            "topic": "goals_constraints",
            "question": "Can you restock the top bestsellers within 3 to 5 days? Any cash or supplier constraint?",
        },
    ]

    return {
        "summary": (
            f"Sales fell {abs(m['sales_change_pct']):g}% ({format_inr(m['sales_last_month'])} → "
            f"{format_inr(m['sales_this_month'])}, i.e. {format_inr(m['sales_change'])}). Average selling price "
            f"is flat at {format_inr(m['asp_this_month'])}, so 100% of the drop is volume: orders fell "
            f"{m['orders_last_month']} → {m['orders_this_month']}."
        ),
        "spoken_numbers": {
            "sales_change": (
                f"sales fell {abs(m['sales_change_pct']):g} percent, about a third, from "
                f"{spoken_inr(m['sales_last_month'])} to {spoken_inr(m['sales_this_month'])}"
            ),
            "sales_drop": spoken_inr(abs(m["sales_change"])),
            "orders": f"orders fell from {m['orders_last_month']} to {m['orders_this_month']}",
            "price": f"average selling price unchanged at {m['asp_this_month']} rupees",
            "cancellations": (
                f"cancellation rate up from {m['cancellation_rate_last_month_pct']:g} to "
                f"{m['cancellation_rate_this_month_pct']:g} percent"
            ),
            "stock_outs": (
                f"out-of-stock products up from {m['out_of_stock_last_month']} to {m['out_of_stock_this_month']}"
            ),
            "lost_on_stock_outs": spoken_inr(oos_value),
            "lost_on_in_stock_products": spoken_inr(in_stock_value),
            "excess_cancellation_cost": spoken_inr(m["excess_cancellation_cost"]),
        },
        "root_cause": (
            "Inventory is the root cause. Bestsellers went out of stock, which directly lost orders. Orders also "
            "kept arriving for items that were not physically available, so they had to be cancelled. Stock-outs "
            "and cancellations push listings down in search, so even in-stock products got fewer views and orders."
        ),
        "drivers": drivers,
        "out_of_stock_bestsellers": bestseller_names,
        "running_low": [
            {"name": s.name, "units_left": s.current_stock, "days_of_cover": s.days_of_cover} for s in at_risk
        ],
        "early_warnings": early_warnings(account),
        "sales_bridge": sales_bridge(account),
        "questions_to_ask": questions,
        "candidate_actions": candidate_actions(account),
        "metrics": m,
        "data_note": (
            "Headline metrics are from the seller dashboard. SKU, traffic and cancellation-reason details are "
            "illustrative assumptions consistent with those totals."
        ),
        "how_to_use": (
            "Share the headline in 2-3 short sentences (orders problem, not pricing; red flags: stock-outs and "
            "cancellations). Then ask ONE question from questions_to_ask. Do not list every number. Later, raise "
            "the most relevant early warning without being asked, and use plan_restock for exact quantities."
        ),
    }


def early_warnings(account: SellerAccount = SELLER) -> list[dict[str, str]]:
    """Things that need attention soon, even though the seller didn't ask about them."""
    warnings = [
        {
            "kind": "running_low",
            "text": (
                f"{s.name}: only {s.current_stock} units left, about {s.days_of_cover:g} days of stock. Reorder now "
                "or it will run out before new stock arrives."
            ),
        }
        for s in _at_risk(account)
    ]
    event = account.upcoming_event
    warnings.append(
        {
            "kind": "deadline",
            "text": (
                f"{event.name} nominations close in {event.nomination_closes_in_days} days. To qualify, each "
                f"nominated product needs {event.min_units}+ units in stock."
            ),
        }
    )
    chronic = account.long_tail.chronic_out_of_stock_skus
    if chronic:
        warnings.append(
            {
                "kind": "catalogue_hygiene",
                "text": (
                    f"{chronic} smaller products have been out of stock since last month. Restock or delist them so "
                    "they stop dragging down the store's in-stock rate."
                ),
            }
        )
    return warnings


def candidate_actions(account: SellerAccount = SELLER) -> list[dict[str, Any]]:
    """Ranked, quantified action options. Disha tailors 2-3 of them to the seller."""
    asp = account.last_month.avg_selling_price_inr
    attribution = order_attribution(account)
    newly_oos = _newly_out_of_stock(account)
    at_risk = _at_risk(account)
    m = headline_metrics(account)
    event = account.upcoming_event
    top_names = ", ".join(s.name for s in newly_oos)
    at_risk_note = (
        " Also reorder " + ", ".join(f"{s.name} (~{s.days_of_cover:g} days of stock left)" for s in at_risk) + "."
        if at_risk
        else ""
    )
    return [
        {
            "rank": 1,
            "title": "Restock the out-of-stock bestsellers first",
            "details": (
                f"Prioritise {top_names}: together they lost {attribution['lost_orders_top_oos']} orders "
                f"(~{format_inr(attribution['lost_orders_top_oos'] * asp)}) this month. Place the order today; "
                f"if the usual supplier is delayed, use a backup supplier for the top two.{at_risk_note}"
            ),
            "expected_impact": (
                f"Recover up to ~{format_inr(attribution['lost_orders_out_of_stock'] * asp)} a month in sales"
            ),
            "owner": "seller",
            "timeline": "Order today, live in 3-5 days",
        },
        {
            "rank": 2,
            "title": "Stop stock-related cancellations",
            "details": (
                "Update Snapdeal stock daily (bulk upload or inventory sync), set unavailable items to zero "
                "immediately, keep a 2-3 unit safety buffer, and turn on low-stock alerts."
            ),
            "expected_impact": (
                f"Bring cancellations from {m['cancellation_rate_this_month_pct']:g}% back under "
                f"{m['cancellation_rate_last_month_pct']:g}%, saving ~{format_inr(m['excess_cancellation_cost'])} "
                "a month and protecting search ranking"
            ),
            "owner": "seller",
            "timeline": "Starting today",
        },
        {
            "rank": 3,
            "title": "Win back visibility once restocked",
            "details": (
                f"Nominate the restocked bestsellers for {event.name} (nominations close in "
                f"{event.nomination_closes_in_days} days; needs {event.requirement.lower()}), or run a 7-day "
                "sponsored-listing boost of about ₹2,000-3,000 on them."
            ),
            "expected_impact": (
                f"Recover the ~{format_inr(attribution['lost_orders_in_stock'] * asp)} lost on in-stock products, "
                "plus festive upside"
            ),
            "owner": "seller (approve) + Disha (set up)",
            "timeline": f"Within {event.nomination_closes_in_days} days",
        },
        {
            "rank": 4,
            "title": "Fix late dispatches",
            "details": "Only if the seller reports courier or packing delays: raise a logistics ticket.",
            "expected_impact": f"Avoid ~{account.cancellations_this_month.late_dispatch} cancellations a month",
            "owner": "Disha (ticket) + seller",
            "timeline": "This week",
        },
    ]


def account_details(area: str, account: SellerAccount = SELLER) -> dict[str, Any]:
    """Drill-down data for one area of the account."""
    asp = account.last_month.avg_selling_price_inr
    if area == "stock":
        tail = account.long_tail
        return {
            "out_of_stock_now": account.this_month.out_of_stock_products,
            "out_of_stock_last_month": account.last_month.out_of_stock_products,
            "active_listings": account.active_listings,
            "bestsellers_out_of_stock": [
                {
                    "name": s.name,
                    "orders_last_month": s.last_month_orders,
                    "orders_this_month": s.this_month_orders,
                    "days_out_of_stock": s.days_out_of_stock,
                    "orders_lost": s.orders_lost,
                    "sales_lost": format_inr(s.orders_lost * asp),
                }
                for s in _newly_out_of_stock(account)
            ],
            "running_low": [
                {"name": s.name, "units_left": s.current_stock, "days_of_cover": s.days_of_cover}
                for s in _at_risk(account)
            ],
            "long_tail": (
                f"{tail.newly_out_of_stock_skus} smaller products also went out of stock this month (lost "
                f"{tail.newly_oos_last_month_orders - tail.newly_oos_this_month_orders} orders); "
                f"{tail.chronic_out_of_stock_skus} have been out of stock since last month."
            ),
        }
    if area == "cancellations":
        lm, tm = account.cancellations_last_month, account.cancellations_this_month
        return {
            "last_month": {
                "total": lm.total,
                "item_unavailable": lm.out_of_stock,
                "late_dispatch": lm.late_dispatch,
                "customer_initiated": lm.customer_initiated,
            },
            "this_month": {
                "total": tm.total,
                "item_unavailable": tm.out_of_stock,
                "late_dispatch": tm.late_dispatch,
                "customer_initiated": tm.customer_initiated,
            },
            "insight": (
                f"Cancellations because the item wasn't available jumped from {lm.out_of_stock} to {tm.out_of_stock} "
                f"and are {round(tm.out_of_stock / tm.total * 100)}% of all cancellations: stock shown on Snapdeal "
                "is not matching physical stock. Late dispatch and customer cancellations actually went down."
            ),
            "why_it_matters": "High seller-side cancellations lower search ranking and seller rating.",
        }
    if area == "visibility":
        views_lm, views_tm = account.product_views_last_month, account.product_views_this_month
        attribution = order_attribution(account)
        return {
            "product_views_last_month": views_lm,
            "product_views_this_month": views_tm,
            "views_change_pct": pct_change(views_lm, views_tm),
            "conversion_last_month_pct": round(account.last_month.orders / views_lm * 100, 2),
            "conversion_this_month_pct": round(account.this_month.orders / views_tm * 100, 2),
            "in_stock_products_orders_lost": attribution["lost_orders_in_stock"],
            "insight": (
                "Views fell because out-of-stock listings drop out of search and the cancellation spike lowers "
                "ranking. Restocking plus a short promotion is the fastest way to recover visibility."
            ),
        }
    if area == "pricing":
        return {
            "avg_selling_price_last_month": format_inr(account.last_month.avg_selling_price_inr),
            "avg_selling_price_this_month": format_inr(account.this_month.avg_selling_price_inr),
            "competitor_price_index": [
                {"name": s.name, "price_vs_lowest_competitor": f"{(s.price_index - 1) * 100:+.0f}%"}
                for s in account.top_skus
            ],
            "insight": (
                "Prices are flat and within ±3% of competitors. Cutting prices would hurt margin without fixing "
                "the real issue, which is availability."
            ),
        }
    if area == "opportunities":
        event = account.upcoming_event
        return {
            "event": event.name,
            "starts_in_days": event.starts_in_days,
            "nomination_closes_in_days": event.nomination_closes_in_days,
            "requirement": event.requirement,
            "expected_uplift": event.expected_uplift,
            "advice": "Restock the bestsellers first; nominate them once they have 20+ units.",
        }
    raise ValueError(f"Unknown area {area!r}")


DETAIL_AREAS = ("stock", "cancellations", "visibility", "pricing", "opportunities")
