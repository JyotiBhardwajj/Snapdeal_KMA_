"""Restock planning: turns "restock your bestsellers" into a concrete purchase order.

For each product that is out of stock or about to run out, the planner works out how many units to order,
what they cost, how much monthly revenue they bring back, and the reorder point to use for low-stock
alerts. Given a budget, it buys the most sales per rupee first and defers the rest to a second phase.

Standard inventory logic, kept deliberately simple and explainable:
    daily demand   = orders per month before the stock-out / 30
    order quantity = one month of demand (minus units still on hand)
    reorder point  = daily demand x (supplier lead time + safety days)
"""

from __future__ import annotations

import math
from typing import Any

from app.formatting import format_inr, spoken_inr
from app.seller_data import SELLER, SellerAccount

UNIT_COST_RATIO = 0.60  # assumed cost of goods as a share of the selling price
DEFAULT_LEAD_TIME_DAYS = 7
SAFETY_DAYS = 7
COVER_DAYS = 30
MIN_PARTIAL_UNITS = 5  # don't suggest token partial orders below this


def _candidates(account: SellerAccount, lead_time_days: int) -> list[dict[str, Any]]:
    asp = account.last_month.avg_selling_price_inr
    unit_cost = round(asp * UNIT_COST_RATIO)
    items: list[dict[str, Any]] = []

    for sku in account.top_skus:
        if sku.is_out_of_stock and sku.days_out_of_stock > 0:
            monthly_orders = sku.last_month_orders  # demand before the stock-out
            units = math.ceil(monthly_orders * COVER_DAYS / 30)
            reason = f"out of stock for {sku.days_out_of_stock} days"
        elif sku.days_of_cover is not None and sku.days_of_cover < lead_time_days + SAFETY_DAYS:
            monthly_orders = max(sku.last_month_orders, sku.this_month_orders)
            units = max(0, math.ceil(monthly_orders * COVER_DAYS / 30) - sku.current_stock)
            reason = f"only {sku.current_stock} left (~{sku.days_of_cover:g} days)"
        else:
            continue
        daily = monthly_orders / 30
        items.append(
            {
                "product": sku.name,
                "spoken": sku.spoken or sku.name.split(" (")[0].lower(),
                "reason": reason,
                "on_hand": sku.current_stock,
                "order_units": units,
                "cost_inr": units * unit_cost,
                "monthly_sales_inr": monthly_orders * asp,
                "reorder_point_units": math.ceil(daily * (lead_time_days + SAFETY_DAYS)),
            }
        )

    tail = account.long_tail
    if tail.newly_oos_last_month_orders:
        units = tail.newly_oos_last_month_orders
        items.append(
            {
                "product": f"{tail.newly_out_of_stock_skus} smaller products (long tail)",
                "spoken": f"units across {tail.newly_out_of_stock_skus} smaller products",
                "reason": "went out of stock this month",
                "on_hand": 0,
                "order_units": units,
                "cost_inr": units * unit_cost,
                "monthly_sales_inr": tail.newly_oos_last_month_orders * asp,
                "reorder_point_units": None,
            }
        )

    # Most monthly sales recovered per rupee first; ties broken by absolute sales.
    for item in items:
        item["sales_per_rupee"] = round(item["monthly_sales_inr"] / item["cost_inr"], 2) if item["cost_inr"] else 0
    items.sort(key=lambda i: (i["sales_per_rupee"], i["monthly_sales_inr"]), reverse=True)
    for rank, item in enumerate(items, start=1):
        item["priority"] = rank
    return items


def _spoken_order(item: dict[str, Any]) -> str:
    """'18 more coffee mug sets (only 6 left)' or '62 water bottle packs (out of stock)'."""
    if item["on_hand"]:
        return f"{item['order_units']} more {item['spoken']} (only {item['on_hand']} left)"
    return f"{item['order_units']} {item['spoken']} (out of stock)"


def restock_plan(
    budget_inr: int | None = None,
    lead_time_days: int | None = None,
    account: SellerAccount = SELLER,
) -> dict[str, Any]:
    lead = lead_time_days if lead_time_days and lead_time_days > 0 else DEFAULT_LEAD_TIME_DAYS
    unit_cost = round(account.last_month.avg_selling_price_inr * UNIT_COST_RATIO)
    items = _candidates(account, lead)
    total_cost = sum(i["cost_inr"] for i in items)
    total_sales = sum(i["monthly_sales_inr"] for i in items)

    plan: dict[str, Any] = {
        "assumptions": {
            "unit_cost_inr": unit_cost,
            "supplier_lead_time_days": lead,
            "safety_days": SAFETY_DAYS,
            "order_covers_days": COVER_DAYS,
        },
        "items": items,
        "full_plan_cost_inr": total_cost,
        "full_plan_monthly_sales_inr": total_sales,
        "budget_inr": budget_inr,
    }

    if budget_inr is not None and budget_inr < total_cost:
        remaining = budget_inr
        funded, deferred = [], []
        for item in items:
            if item["cost_inr"] <= remaining:
                funded.append({**item})
                remaining -= item["cost_inr"]
                continue
            units = remaining // unit_cost
            if units >= MIN_PARTIAL_UNITS and item["order_units"]:
                share = units / item["order_units"]
                funded.append(
                    {
                        **item,
                        "order_units": units,
                        "cost_inr": units * unit_cost,
                        "monthly_sales_inr": round(item["monthly_sales_inr"] * share),
                        "partial": True,
                    }
                )
                remaining -= units * unit_cost
                deferred.append(item["product"] + " (rest)")
            else:
                deferred.append(item["product"])
        covered = sum(i["monthly_sales_inr"] for i in funded)
        plan.update(
            {
                "within_budget": funded,
                "budget_used_inr": budget_inr - remaining,
                "monthly_sales_covered_inr": covered,
                "deferred_to_phase_2": deferred,
                "summary": (
                    f"With {format_inr(budget_inr)}: order "
                    + ", ".join(f"{i['order_units']} x {i['product']}" for i in funded)
                    + f" (brings back ~{format_inr(covered)} a month). Phase 2, from the cash these sales generate: "
                    + ", ".join(deferred)
                    + f". Full plan: {format_inr(total_cost)} for ~{format_inr(total_sales)} a month."
                ),
                "spoken_hint": (
                    f"With {spoken_inr(budget_inr)} you can restock "
                    + " and ".join(_spoken_order(i) for i in funded[:3])
                    + f", which brings back about {spoken_inr(covered)} a month; the rest can follow in a second phase."
                ),
            }
        )
    else:
        plan.update(
            {
                "summary": (
                    f"Restocking everything costs about {format_inr(total_cost)} and brings back about "
                    f"{format_inr(total_sales)} of monthly sales. Set low-stock alerts at the reorder points "
                    f"(they include the {lead}-day supplier lead time plus a {SAFETY_DAYS}-day safety buffer)."
                ),
                "spoken_hint": (
                    f"Restocking all {len(items)} items costs about {spoken_inr(total_cost)} and brings back about "
                    f"{spoken_inr(total_sales)} a month. Biggest wins first: "
                    + " and ".join(_spoken_order(i) for i in items[:2])
                    + f", about {spoken_inr(sum(i['cost_inr'] for i in items[:2]))} for "
                    f"{spoken_inr(sum(i['monthly_sales_inr'] for i in items[:2]))} a month."
                ),
            }
        )
    return plan
