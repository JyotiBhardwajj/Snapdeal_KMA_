"""Tool layer: validation, consent, idempotency and case-file side effects."""

import pytest

from app.case_file import CaseFile
from app.tools import ACTIONS, TOOL_DECLARATIONS, ToolExecutor, tool_declarations


@pytest.fixture
def executor():
    return ToolExecutor(CaseFile.open(mode="inbound", language="en"))


def test_every_declared_tool_has_a_handler_and_vice_versa(executor):
    declared = {d.name for d in TOOL_DECLARATIONS}
    assert declared == set(executor._handlers)


def test_analyze_populates_diagnosis_and_hides_ui_only_fields(executor):
    result = executor.execute("analyze_sales_drop", {})
    assert "sales_bridge" not in result
    assert result["drivers"][0]["key"] == "stock"
    assert executor.case.diagnosis["sales_bridge"][0]["value"] == 200_000
    assert executor.case.activity[-1]["tool"] == "analyze_sales_drop"


def test_unknown_tool_and_bad_enum_are_reported_not_raised(executor):
    assert "error" in executor.execute("delete_account", {})
    assert "error" in executor.execute("get_account_details", {"area": "weather"})
    assert executor.case.activity[-1]["ok"] is False


def test_record_insight_dedupes(executor):
    args = {"topic": "stock_and_supply", "insight": "Supplier delayed stock by 3 weeks"}
    executor.execute("record_seller_insight", args)
    executor.execute("record_seller_insight", {**args, "insight": "supplier delayed stock by 3 weeks"})
    assert len(executor.case.insights) == 1


def test_save_action_plan_validates_and_normalises(executor):
    assert "error" in executor.execute("save_action_plan", {"actions": [], "kpi_targets": []})
    result = executor.execute(
        "save_action_plan",
        {
            "actions": [
                {
                    "title": "Restock top 4",
                    "details": "Order today",
                    "expected_impact": "₹56,000/month",
                    "owner": "intern",
                    "timeline": "3 days",
                }
            ],
            "kpi_targets": ["OOS <= 5 in 7 days"],
        },
    )
    assert result["status"] == "saved"
    assert executor.case.action_plan[0]["owner"] == "seller"  # unknown owner normalised
    assert executor.case.kpi_targets == ["OOS <= 5 in 7 days"]


def test_take_action_requires_explicit_consent(executor):
    result = executor.execute(
        "take_action", {"action": "set_low_stock_alerts", "details": "", "seller_confirmed": False}
    )
    assert "error" in result
    assert executor.case.actions_taken == []


def test_take_action_is_idempotent(executor):
    args = {"action": "send_restock_priority_list", "details": "top 4", "seller_confirmed": True}
    first = executor.execute("take_action", args)
    second = executor.execute("take_action", args)
    assert first["status"] == "done"
    assert second["status"] == "already_done"
    assert second["reference_id"] == first["reference_id"]
    assert len(executor.case.actions_taken) == 1


@pytest.mark.parametrize("action", list(ACTIONS))
def test_every_action_has_a_confirmation(executor, action):
    result = executor.execute("take_action", {"action": action, "details": "x", "seller_confirmed": True})
    assert result["status"] == "done" and result["confirmation"]


def test_follow_up_needs_the_sellers_yes(executor):
    result = executor.execute("schedule_follow_up", {"days_from_now": 7, "agenda": "Review", "seller_agreed": False})
    assert "error" in result and executor.case.follow_up is None


def test_follow_up_is_rescheduled_not_double_booked(executor):
    first = executor.execute("schedule_follow_up", {"days_from_now": 7, "agenda": "Review", "seller_agreed": True})
    second = executor.execute("schedule_follow_up", {"days_from_now": 8, "agenda": "Review", "seller_agreed": True})
    assert second["reference_id"] == first["reference_id"]
    assert "Sunday" not in second["when"]
    bad = executor.execute("schedule_follow_up", {"days_from_now": "soon", "agenda": "x", "seller_agreed": True})
    assert "error" in bad


def test_end_call_marks_case_ending(executor):
    args = {"key_issues": ["Stock-outs"], "recommendations": ["Restock"], "next_steps": ["Seller restocks"]}
    first = executor.execute("end_call_with_summary", args)
    second = executor.execute("end_call_with_summary", args)
    assert first["status"] == "saved_and_sent" and second["status"] == "updated"
    assert executor.case.call_ending is True
    assert executor.case.summary["key_issues"] == ["Stock-outs"]


def test_label_is_human_readable():
    assert ToolExecutor.label("take_action", {"action": "set_low_stock_alerts"}) == "Set low-stock alerts"
    assert ToolExecutor.label("get_account_details", {"area": "stock"}) == "Checking stock details"


def test_tools_offered_depend_on_call_mode():
    first_call = {d.name for d in tool_declarations("inbound")}
    follow_up = {d.name for d in tool_declarations("followup")}
    assert "analyze_sales_drop" in first_call and "review_progress" not in first_call
    assert "review_progress" in follow_up and "analyze_sales_drop" not in follow_up
    assert {"plan_restock", "take_action", "end_call_with_summary"} <= first_call & follow_up


def test_plan_restock_validates_and_stores_plan(executor):
    assert "error" in executor.execute("plan_restock", {"budget_inr": "lots"})
    result = executor.execute("plan_restock", {"budget_inr": 25000, "supplier_lead_time_days": 21})
    assert result["within_budget"] and executor.case.restock_plan["budget_inr"] == 25000
    alerts = executor.execute(
        "take_action", {"action": "set_low_stock_alerts", "details": "", "seller_confirmed": True}
    )
    assert "at 58 units" in alerts["confirmation"]  # water bottle reorder point with a 21-day lead time


def test_review_progress_uses_previous_case():
    previous = {"case_id": "CASE-PREV01", "action_plan": [{"title": "Think about pricing"}], "actions_taken": []}
    executor = ToolExecutor(CaseFile.open(mode="followup", language="en"), previous_case=previous)
    result = executor.execute("review_progress", {})
    assert result["agreed_last_time"]["plan"] == ["Think about pricing"]
    assert executor.case.progress["kpis"][0]["metric"] == "Weekly sales"


def test_follow_up_call_knows_a_week_has_passed():
    executor = ToolExecutor(CaseFile.open(mode="followup", language="en"))
    result = executor.execute(
        "take_action", {"action": "nominate_for_sale_event", "details": "", "seller_confirmed": True}
    )
    assert "close in 2 days" in result["confirmation"]
