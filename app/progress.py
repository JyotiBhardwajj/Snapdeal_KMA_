"""The 7-day follow-up call: closing the loop on the action plan.

Ownership doesn't stop when the first call ends. Disha calls back a week later, as booked, and reviews
progress against the targets she set. The week-later numbers are simulated for the demo, but they are driven
by what was actually agreed on the first call (restocking, daily stock updates, alerts, sale nomination), so
different first calls lead to different follow-up conversations. Everything is deterministic and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.diagnostics import running_low
from app.formatting import format_inr, pct_change, spoken_inr
from app.planning import restock_plan
from app.seller_data import SELLER, SellerAccount, Sku

DAYS_SINCE_FIRST_CALL = 7

# What a typical first call agrees on; used when the follow-up is started without a previous call.
DEFAULT_PREVIOUS_CASE: dict[str, Any] = {
    "case_id": "CASE-DEMO01",
    "action_plan": [
        {"title": "Restock the 4 out-of-stock bestsellers", "expected_impact": "₹56,000/month", "owner": "seller"},
        {
            "title": "Update stock daily with a safety buffer",
            "expected_impact": "Cancellations under 8%",
            "owner": "seller",
        },
        {"title": "Nominate restocked bestsellers for Savings Week", "expected_impact": "Win back visibility"},
    ],
    "kpi_targets": [
        "Out-of-stock products back to 5 or fewer",
        "Cancellation rate under 8%",
        "Weekly sales back to about ₹46,500",
    ],
    "actions_taken": [
        {"action": "set_low_stock_alerts", "label": "Set low-stock alerts"},
        {"action": "send_restock_priority_list", "label": "Sent restock priority list"},
    ],
    "summary": {},
    "insights": [
        {"topic": "stock_and_supply", "insight": "Main supplier delayed stock by about three weeks (festive rush)."},
        {"topic": "inventory_process", "insight": "Updates stock on Snapdeal manually, once a week."},
    ],
}


@dataclass(frozen=True)
class Commitments:
    restock: bool
    inventory_process: bool
    alerts: bool
    nominated: bool
    running_low_covered: bool


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if value is not None else ""


def sanitize_previous_case(raw: Any) -> dict[str, Any] | None:
    """Keep only known fields, with length limits: the client sends this, so treat it as untrusted."""
    if not isinstance(raw, dict):
        return None

    def items(key: str, limit: int) -> list:
        value = raw.get(key)
        return [v for v in value[:limit] if isinstance(v, dict)] if isinstance(value, list) else []

    def strings(value: Any, limit: int, length: int) -> list[str]:
        return [_clean(v, length) for v in value[:limit] if isinstance(v, str)] if isinstance(value, list) else []

    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    restock = raw.get("restock_plan") if isinstance(raw.get("restock_plan"), dict) else {}
    restock_items = restock.get("items") if isinstance(restock.get("items"), list) else []
    case = {
        "case_id": _clean(raw.get("case_id"), 24),
        "action_plan": [
            {k: _clean(a.get(k), 300) for k in ("title", "details", "expected_impact", "owner", "timeline")}
            for a in items("action_plan", 4)
        ],
        "kpi_targets": strings(raw.get("kpi_targets"), 4, 160),
        "actions_taken": [
            {k: _clean(a.get(k), 200) for k in ("action", "label", "details", "reference_id")}
            for a in items("actions_taken", 8)
        ],
        "summary": {k: strings(summary.get(k), 6, 240) for k in ("key_issues", "recommendations", "next_steps")},
        "insights": [{k: _clean(i.get(k), 240) for k in ("topic", "insight")} for i in items("insights", 6)],
        "restock_products": [_clean(i.get("product"), 80) for i in restock_items[:8] if isinstance(i, dict)],
    }
    if not (case["action_plan"] or case["actions_taken"] or any(case["summary"].values())):
        return None
    return case


def _keywords(sku: Sku) -> set[str]:
    """Distinctive words of a product name, e.g. 'Ceramic Coffee Mugs (set of 4)' -> {ceramic, coffee, mug}."""
    words = sku.name.split("(")[0].lower().replace(",", " ").split()
    return {w.rstrip("s") for w in words if len(w) >= 4}


def commitments_from(previous: dict[str, Any], account: SellerAccount = SELLER) -> Commitments:
    actions = {a.get("action") for a in previous.get("actions_taken", [])}
    summary = previous.get("summary") or {}
    text = " ".join(
        [f"{a.get('title', '')} {a.get('details', '')}" for a in previous.get("action_plan", [])]
        + list(summary.get("recommendations", []))
        + list(summary.get("next_steps", []))
        + list(previous.get("restock_products", []))
    ).lower()
    restock = any(k in text for k in ("restock", "reorder", "replenish")) or "send_restock_priority_list" in actions
    process = any(
        k in text for k in ("daily", "update stock", "update your stock", "inventory", "sync", "buffer")
    ) or bool({"set_low_stock_alerts", "pause_unavailable_listings"} & actions)
    return Commitments(
        restock=restock,
        inventory_process=process,
        alerts="set_low_stock_alerts" in actions,
        nominated="nominate_for_sale_event" in actions,
        running_low_covered=all(any(k in text for k in _keywords(sku)) for sku in running_low(account)),
    )


def _status(baseline: float, target: float, now: float, higher_is_better: bool) -> str:
    if higher_is_better:
        met, progress = now >= target, (now - baseline) / (target - baseline)
    else:
        met, progress = now <= target, (baseline - now) / (baseline - target)
    if met:
        return "met"
    if progress >= 0.5:
        return "on_track"
    return "behind" if progress > 0 else "off_track"


def review_progress(previous: dict[str, Any] | None = None, account: SellerAccount = SELLER) -> dict[str, Any]:
    previous = previous or DEFAULT_PREVIOUS_CASE
    c = commitments_from(previous, account)
    asp = account.this_month.avg_selling_price_inr
    base_orders = round(account.this_month.orders / 30 * 7)
    target_orders = round(account.last_month.orders / 30 * 7)
    oos_target = account.last_month.out_of_stock_products

    # Simulated last-7-day outcomes for each combination of commitments.
    if c.restock and c.inventory_process:
        orders, cancel_rate, oos, views_change = 78, 0.05, 9, 18
    elif c.restock:
        orders, cancel_rate, oos, views_change = 74, 0.11, 9, 14
    elif c.inventory_process:
        orders, cancel_rate, oos, views_change = 66, 0.07, 17, 3
    else:
        orders, cancel_rate, oos, views_change = 61, 0.13, 18, -2

    sales_now, sales_base, sales_target = orders * asp, base_orders * asp, target_orders * asp
    kpis = [
        {
            "metric": "Weekly sales",
            "unit": "inr",
            "before": sales_base,
            "target": sales_target,
            "now": sales_now,
            "status": _status(sales_base, sales_target, sales_now, True),
        },
        {
            "metric": "Out-of-stock products",
            "unit": "count",
            "before": account.this_month.out_of_stock_products,
            "target": oos_target,
            "now": oos,
            "status": _status(account.this_month.out_of_stock_products, oos_target, oos, False),
        },
        {
            "metric": "Cancellation rate",
            "unit": "ratio",
            "before": account.this_month.cancellation_rate,
            "target": account.last_month.cancellation_rate,
            "now": cancel_rate,
            "status": _status(
                account.this_month.cancellation_rate, account.last_month.cancellation_rate, cancel_rate, False
            ),
        },
    ]

    sales_change = round(pct_change(sales_base, sales_now))
    wins, open_items, new_risks, opportunities, next_actions = [], [], [], [], []
    event = account.upcoming_event
    nomination_days_left = event.nomination_closes_in_days - DAYS_SINCE_FIRST_CALL

    if c.restock:
        wins.append("Water bottles, kitchen towels and glass jars are back in stock (restocked 3 days ago)")
        open_items.append(
            "Wooden Spice Rack still out of stock: the supplier shipped half the order; rest due in 4 days"
        )
        next_actions.append("Chase the spice rack batch, or use a backup supplier for it")
    else:
        open_items.append("The 4 bestsellers are still out of stock; this is still the biggest lever")
        next_actions.append("Place the restock order for the bestsellers today (use plan_restock for quantities)")
    if sales_change > 0:
        wins.append(f"Weekly sales up {sales_change:g}% ({format_inr(sales_base)} → {format_inr(sales_now)})")
    if cancel_rate <= account.last_month.cancellation_rate:
        wins.append(f"Cancellations down to {cancel_rate:.0%} this week, better than the 8% target")
    else:
        open_items.append(f"Cancellations still {cancel_rate:.0%}: stock on Snapdeal isn't updated often enough")
        next_actions.append("Switch to daily stock updates and turn on low-stock alerts")
    if oos > oos_target:
        open_items.append(f"{oos} products still out of stock against a target of {oos_target}")

    if not c.running_low_covered:
        plan_items = {i["product"]: i for i in restock_plan(account=account)["items"]}
        for sku in running_low(account):
            short = sku.name.split(" (")[0]
            item = plan_items.get(sku.name)
            new_risks.append(
                f"{short} are down to 1 unit and will run out in a day or two "
                f"(flagged at {sku.current_stock} last week)"
            )
            if item:
                next_actions.insert(
                    0, f"Reorder {item['order_units']} {item['spoken']} today (about {format_inr(item['cost_inr'])})"
                )
    if c.nominated:
        starts_in = event.starts_in_days - DAYS_SINCE_FIRST_CALL
        wins.append(f"{event.name}: 3 restocked bestsellers confirmed; the sale starts in {starts_in} days")
    elif c.restock:
        opportunities.append(
            f"{event.name} nominations close in {nomination_days_left} days, and the 3 restocked bestsellers now "
            f"qualify ({event.min_units}+ units each)"
        )
        next_actions.append("Nominate the 3 restocked bestsellers for Savings Week before nominations close")

    agreed = {
        "plan": [a.get("title") for a in previous.get("action_plan", []) if a.get("title")],
        "done_by_disha": [a.get("label") for a in previous.get("actions_taken", []) if a.get("label")],
        "targets": previous.get("kpi_targets", []),
    }
    return {
        "period": f"Last {DAYS_SINCE_FIRST_CALL} days vs. the week before the first call",
        "agreed_last_time": agreed,
        "kpis": kpis,
        "wins": wins,
        "open_items": open_items,
        "new_risks": new_risks,
        "opportunities": opportunities,
        "suggested_next_actions": next_actions[:4],
        "views_change_pct": views_change,
        "spoken_numbers": {
            "weekly_sales": (
                f"weekly sales {'up' if sales_change >= 0 else 'down'} {abs(sales_change):g} percent, from "
                f"{spoken_inr(sales_base)} to {spoken_inr(sales_now)}"
            ),
            "cancellations": f"cancellation rate {round(cancel_rate * 100)} percent this week, target under 8",
            "stock_outs": f"{oos} products out of stock, down from 18, target {oos_target}",
        },
        "how_to_use": (
            "Lead with the wins (with numbers), then what's behind the targets, then the new risk or opportunity. "
            "Ask ONE question about the biggest open item."
        ),
        "data_note": "Week-later metrics are simulated for the demo, based on what was agreed on the first call.",
    }
