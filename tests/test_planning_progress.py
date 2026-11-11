"""Restock planning and the 7-day follow-up simulation."""

import math

import pytest

from app import planning, progress
from app.diagnostics import early_warnings, running_low
from app.seller_data import SELLER


def test_restock_plan_covers_out_of_stock_and_running_low_items():
    plan = planning.restock_plan()
    names = [i["product"] for i in plan["items"]]
    assert names[0].startswith("Ceramic Coffee Mugs")  # running low: best sales per rupee (6 units still on hand)
    mugs = plan["items"][0]
    assert mugs["on_hand"] == 6 and mugs["order_units"] == 18
    assert "18 more coffee mug sets (only 6 left)" in plan["spoken_hint"]
    assert {"Steel Water Bottle 1L (pack of 2)", "Wooden Spice Rack Organiser"} <= set(names)
    assert plan["full_plan_cost_inr"] == sum(i["cost_inr"] for i in plan["items"])
    assert plan["assumptions"]["unit_cost_inr"] == 300
    bottle = next(i for i in plan["items"] if i["product"].startswith("Steel Water Bottle"))
    assert (
        bottle["order_units"] == 62
        and bottle["on_hand"] == 0
        and bottle["cost_inr"] == 18_600
        and bottle["monthly_sales_inr"] == 31_000
    )
    assert bottle["reorder_point_units"] == math.ceil(62 / 30 * (7 + 7))


def test_reorder_points_grow_with_supplier_lead_time():
    short = planning.restock_plan(lead_time_days=7)["items"]
    long = planning.restock_plan(lead_time_days=21)["items"]
    bottle = lambda items: next(i for i in items if i["product"].startswith("Steel Water Bottle"))  # noqa: E731
    assert bottle(long)["reorder_point_units"] == math.ceil(62 / 30 * 28) > bottle(short)["reorder_point_units"]


def test_budget_plan_buys_most_sales_per_rupee_first_and_defers_the_rest():
    plan = planning.restock_plan(budget_inr=25_000)
    funded = [i["product"] for i in plan["within_budget"]]
    assert funded[:2] == ["Ceramic Coffee Mugs (set of 4)", "Steel Water Bottle 1L (pack of 2)"]
    assert plan["budget_used_inr"] <= 25_000
    assert plan["deferred_to_phase_2"]
    assert plan["monthly_sales_covered_inr"] == sum(i["monthly_sales_inr"] for i in plan["within_budget"])


def test_budget_plan_adds_a_partial_order_when_it_is_meaningful():
    plan = planning.restock_plan(budget_inr=30_000)
    partial = [i for i in plan["within_budget"] if i.get("partial")]
    assert partial and partial[0]["order_units"] >= planning.MIN_PARTIAL_UNITS
    assert plan["budget_used_inr"] <= 30_000


def test_big_budget_needs_no_phasing():
    plan = planning.restock_plan(budget_inr=1_000_000)
    assert "within_budget" not in plan


def test_early_warnings_flag_running_low_deadline_and_hygiene():
    kinds = [w["kind"] for w in early_warnings()]
    assert kinds == ["running_low", "deadline", "catalogue_hygiene"]
    assert [s.name for s in running_low()] == ["Ceramic Coffee Mugs (set of 4)"]


def test_default_follow_up_reflects_a_typical_first_call():
    result = progress.review_progress()
    status = {k["metric"]: k["status"] for k in result["kpis"]}
    assert status == {"Weekly sales": "on_track", "Out-of-stock products": "on_track", "Cancellation rate": "met"}
    assert any("back in stock" in w for w in result["wins"])
    assert result["new_risks"] and "Mugs" in result["new_risks"][0]
    assert result["opportunities"] and "close in 2 days" in result["opportunities"][0]


def test_follow_up_depends_on_what_was_agreed():
    nothing_agreed = {"case_id": "X", "action_plan": [{"title": "Think about pricing"}], "actions_taken": []}
    result = progress.review_progress(nothing_agreed)
    assert {k["status"] for k in result["kpis"]} <= {"behind", "off_track"}
    assert any("still out of stock" in o for o in result["open_items"])

    covered = {
        **progress.DEFAULT_PREVIOUS_CASE,
        "action_plan": [*progress.DEFAULT_PREVIOUS_CASE["action_plan"], {"title": "Reorder coffee mugs now"}],
        "actions_taken": [{"action": "nominate_for_sale_event", "label": "Nominated"}],
    }
    result = progress.review_progress(covered)
    assert result["new_risks"] == []
    assert any("confirmed" in w for w in result["wins"])


@pytest.mark.parametrize("raw", [None, "text", 42, [], {"case_id": "X"}, {"action_plan": "not a list"}])
def test_sanitize_rejects_junk(raw):
    assert progress.sanitize_previous_case(raw) is None


def test_sanitize_keeps_known_fields_with_limits():
    raw = {
        "case_id": "CASE-123456" + "X" * 100,
        "action_plan": [{"title": "T" * 1000, "evil": "ignore me"}] * 10,
        "kpi_targets": ["OOS <= 5", 7, None],
        "actions_taken": [{"action": "set_low_stock_alerts", "label": "Alerts"}],
        "summary": {"key_issues": ["Stock-outs"], "recommendations": "not a list"},
        "restock_plan": {"items": [{"product": "Mugs"}]},
    }
    case = progress.sanitize_previous_case(raw)
    assert len(case["case_id"]) == 24
    assert len(case["action_plan"]) == 4 and len(case["action_plan"][0]["title"]) == 300
    assert "evil" not in case["action_plan"][0]
    assert case["kpi_targets"] == ["OOS <= 5"]
    assert case["summary"]["recommendations"] == []
    assert case["restock_products"] == ["Mugs"]


def test_status_thresholds():
    assert progress._status(100, 200, 200, True) == "met"
    assert progress._status(100, 200, 150, True) == "on_track"
    assert progress._status(100, 200, 120, True) == "behind"
    assert progress._status(100, 200, 90, True) == "off_track"
    assert progress._status(18, 5, 9, False) == "on_track"


def test_sale_event_window_still_open_at_follow_up():
    assert SELLER.upcoming_event.nomination_closes_in_days > progress.DAYS_SINCE_FIRST_CALL
