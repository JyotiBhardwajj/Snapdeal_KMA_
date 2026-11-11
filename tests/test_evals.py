"""The evaluation harness itself: scenario definitions, ground truth and automated checks."""

from evals.run_evals import CRITERIA, _checks, _ground_truth
from evals.scenarios import SCENARIOS, ToolExpectation


def test_scenario_ids_are_unique_and_cover_all_modes():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert {s.mode for s in SCENARIOS} == {"inbound", "outbound", "followup"}
    assert {s.language for s in SCENARIOS} == {"en", "hi"}


def test_ground_truth_builds_for_every_scenario():
    for scenario in SCENARIOS:
        text = _ground_truth(scenario)
        assert "₹" in text and len(text) > 200


def test_tool_expectation_matching():
    ticket = ToolExpectation("take_action", "action", "raise_support_ticket")
    assert ticket.matches({"tool": "take_action", "args": {"action": "raise_support_ticket"}})
    assert not ticket.matches({"tool": "take_action", "args": {"action": "set_low_stock_alerts"}})
    assert ToolExpectation("plan_restock", "budget_inr").matches(
        {"tool": "plan_restock", "args": {"budget_inr": 25000}}
    )
    assert not ToolExpectation("plan_restock", "budget_inr").matches({"tool": "plan_restock", "args": {}})
    assert ticket.describe() == "take_action(action=raise_support_ticket)"


def test_automated_checks():
    scenario = next(s for s in SCENARIOS if s.id == "cooperative")
    run = {
        "transcript": [
            {"role": "disha", "text": "Hello Rajesh, how can I help?"},
            {"role": "seller", "text": "Sales dropped."},
            {"role": "disha", "text": "Sales fell a third. What caused the stock-outs? And how do you update stock?"},
            {"role": "seller", "text": "Supplier delay."},
            {"role": "disha", "text": "Thanks, goodbye!"},
        ],
        "tool_log": [
            {"tool": "analyze_sales_drop", "args": {}, "status": "ok"},
            {"tool": "take_action", "args": {"action": "x"}, "status": "already_done"},
        ],
    }
    checks = _checks(scenario, run)
    assert "save_action_plan" in checks["required_tools_missing"]
    assert checks["multi_question_turns"] == 1
    assert checks["duplicate_actions"] == 1
    assert checks["turns"] == 5


def test_criteria_match_the_verdict_schema():
    from evals.run_evals import Verdict

    assert {key for key, _ in CRITERIA} <= set(Verdict.model_fields)
