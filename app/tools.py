"""Function-calling tools available to the voice agent.

Two kinds of tools:
  * Insight tools (read): run the diagnostics engine / drill into account data.
  * Ownership tools (write): record what the seller said, commit an action plan,
    execute actions on the seller's behalf (only with explicit consent), book a
    follow-up and close the case with a summary.

All "write" side effects are simulated (no real Snapdeal systems), but they are
modelled the way a production integration would be: validated arguments,
consent checks, reference IDs and an auditable activity log.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from google.genai import types

from app import diagnostics, planning, progress
from app.case_file import CaseFile, new_reference, now_ist
from app.seller_data import SELLER, SellerAccount


class ToolArgumentError(ValueError):
    """Raised when the model sends invalid arguments; reported back to the model."""


INSIGHT_TOPICS = (
    "stock_and_supply",
    "inventory_process",
    "cancellations",
    "pricing_competition",
    "listings_and_visibility",
    "operations",
    "goals_constraints",
    "other",
)

OWNERS = ("seller", "disha", "snapdeal_team", "seller_and_disha")

ACTIONS: dict[str, str] = {
    "set_low_stock_alerts": "Set low-stock alerts",
    "pause_unavailable_listings": "Paused unavailable listings",
    "nominate_for_sale_event": "Nominated products for sale event",
    "create_sponsored_ads_draft": "Drafted sponsored-listing campaign",
    "send_restock_priority_list": "Sent restock priority list",
    "raise_support_ticket": "Raised support ticket",
    "request_human_kam_callback": "Requested human KAM callback",
}

_STR = {"type": "STRING"}

TOOL_DECLARATIONS: list[types.FunctionDeclaration] = [
    types.FunctionDeclaration(
        name="analyze_sales_drop",
        description=(
            "Run the diagnostics engine on the seller's account: month-over-month metrics, a sales bridge, "
            "verdicts on each possible cause (stock-outs, cancellations, visibility, pricing) with rupee impact, "
            "questions worth asking, and ranked candidate actions. Call this as soon as the seller raises any "
            "sales or performance concern, BEFORE quoting any numbers."
        ),
    ),
    types.FunctionDeclaration(
        name="get_account_details",
        description=(
            "Drill into one area of the seller's account when you need specifics: which products are out of "
            "stock or running low, why orders were cancelled, traffic and conversion, competitor prices, or "
            "upcoming sale opportunities."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {"area": {"type": "STRING", "enum": list(diagnostics.DETAIL_AREAS)}},
            "required": ["area"],
        },
    ),
    types.FunctionDeclaration(
        name="plan_restock",
        description=(
            "Build a concrete restock order: units, cost, monthly sales brought back and the reorder point for each "
            "product that is out of stock or about to run out, most sales per rupee first. If the seller mentioned "
            "ANY budget or cash limit, you must pass budget_inr (it then fits the order to the budget and phases the "
            "rest). Pass supplier_lead_time_days if they told you how long their supplier takes. Use it whenever you "
            "recommend restocking or are asked what or how much to reorder. Quote its spoken_hint numbers as given."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "budget_inr": {"type": "INTEGER", "description": "Cash available for restocking, in rupees."},
                "supplier_lead_time_days": {"type": "INTEGER", "description": "Days from order to stock arriving."},
            },
        },
    ),
    types.FunctionDeclaration(
        name="review_progress",
        description=(
            "Follow-up calls only: compare the last 7 days with the targets agreed on the previous call, and list "
            "wins, open items, new risks and opportunities. Call it first in a follow-up call."
        ),
    ),
    types.FunctionDeclaration(
        name="record_seller_insight",
        description=(
            "Save an important fact the seller just told you (e.g. supplier delayed stock by 3 weeks, updates "
            "inventory manually once a week, cash-flow constraint). Call it right after the seller shares it."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "enum": list(INSIGHT_TOPICS)},
                "insight": {"type": "STRING", "description": "One-sentence paraphrase of what the seller said."},
            },
            "required": ["topic", "insight"],
        },
    ),
    types.FunctionDeclaration(
        name="save_action_plan",
        description=(
            "Save the 2-3 recommendations you are giving the seller (most impactful first), tailored to what "
            "they told you, plus measurable targets. Call it when you present your recommendations."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "actions": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {
                                "type": "STRING",
                                "description": "Short imperative, e.g. 'Restock top 4 bestsellers'",
                            },
                            "details": {"type": "STRING", "description": "What exactly to do, tailored to the seller."},
                            "expected_impact": {
                                "type": "STRING",
                                "description": "Impact from the data, written with digits, e.g. '₹56,000/month'.",
                            },
                            "owner": {"type": "STRING", "enum": list(OWNERS)},
                            "timeline": {"type": "STRING", "description": "e.g. 'within 3 days'"},
                        },
                        "required": ["title", "details", "expected_impact", "owner", "timeline"],
                    },
                },
                "kpi_targets": {
                    "type": "ARRAY",
                    "items": _STR,
                    "description": "e.g. 'Out-of-stock products back to 5 or fewer within 7 days'",
                },
            },
            "required": ["actions", "kpi_targets"],
        },
    ),
    types.FunctionDeclaration(
        name="take_action",
        description=(
            "Do something on the seller's behalf. ONLY call this after the seller has explicitly agreed, and set "
            "seller_confirmed=true. Actions: set_low_stock_alerts, pause_unavailable_listings (stops new orders "
            "on items they cannot fulfil, so no more cancellations), nominate_for_sale_event, "
            "create_sponsored_ads_draft (nothing is spent until the seller approves), send_restock_priority_list "
            "(WhatsApps the exact restock order with units and cost per product, for their supplier: use it whenever "
            "the seller agrees to reorder anything), raise_support_ticket, request_human_kam_callback."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(ACTIONS)},
                "details": {"type": "STRING", "description": "Specifics agreed with the seller."},
                "seller_confirmed": {"type": "BOOLEAN"},
            },
            "required": ["action", "details", "seller_confirmed"],
        },
    ),
    types.FunctionDeclaration(
        name="schedule_follow_up",
        description="Book a follow-up call with the seller to review progress against the action plan and targets.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "days_from_now": {"type": "INTEGER", "description": "1-30, usually 7."},
                "agenda": {"type": "STRING"},
                "seller_agreed": {"type": "BOOLEAN", "description": "True only if the seller said yes to a follow-up."},
            },
            "required": ["days_from_now", "agenda", "seller_agreed"],
        },
    ),
    types.FunctionDeclaration(
        name="end_call_with_summary",
        description=(
            "Call this when the conversation is wrapping up. Saves the call summary to the case file and sends "
            "it to the seller on WhatsApp. After it returns, speak a short summary and say goodbye."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "key_issues": {"type": "ARRAY", "items": _STR},
                "recommendations": {"type": "ARRAY", "items": _STR},
                "next_steps": {
                    "type": "ARRAY",
                    "items": _STR,
                    "description": "Who does what by when, including what Disha will do.",
                },
            },
            "required": ["key_issues", "recommendations", "next_steps"],
        },
    ),
]


FIRST_CALL_ONLY = {"analyze_sales_drop"}
FOLLOW_UP_ONLY = {"review_progress"}


def tool_declarations(mode: str) -> list[types.FunctionDeclaration]:
    """Tools offered to the model for a given call mode."""
    excluded = FIRST_CALL_ONLY if mode == "followup" else FOLLOW_UP_ONLY
    return [d for d in TOOL_DECLARATIONS if d.name not in excluded]


# --- argument validation helpers --------------------------------------------------------


def _text(args: dict[str, Any], key: str, *, max_len: int = 400, required: bool = True) -> str:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolArgumentError(f"'{key}' is required")
        return ""
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.split())[:max_len]


def _choice(args: dict[str, Any], key: str, choices: tuple[str, ...] | list[str]) -> str:
    value = _text(args, key, max_len=64)
    if value not in choices:
        raise ToolArgumentError(f"'{key}' must be one of {list(choices)}")
    return value


def _str_list(args: dict[str, Any], key: str, *, max_items: int = 6, max_len: int = 300) -> list[str]:
    value = args.get(key) or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ToolArgumentError(f"'{key}' must be a list of strings")
    items = [" ".join(str(v).split())[:max_len] for v in value if str(v).strip()]
    return items[:max_items]


def _optional_int(args: dict[str, Any], key: str, lo: int, hi: int) -> int | None:
    if args.get(key) in (None, "", 0):
        return None
    return _int_in(args, key, lo, hi)


def _int_in(args: dict[str, Any], key: str, lo: int, hi: int) -> int:
    try:
        value = int(float(args.get(key)))
    except (TypeError, ValueError) as exc:
        raise ToolArgumentError(f"'{key}' must be an integer") from exc
    return max(lo, min(hi, value))


# --- executor ---------------------------------------------------------------------------


class ToolExecutor:
    """Executes tool calls against one call's case file."""

    def __init__(
        self,
        case: CaseFile,
        account: SellerAccount = SELLER,
        previous_case: dict[str, Any] | None = None,
    ) -> None:
        self.case = case
        self.account = account
        self.previous_case = previous_case
        self._lead_time_days: int | None = None
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "analyze_sales_drop": self._analyze_sales_drop,
            "get_account_details": self._get_account_details,
            "plan_restock": self._plan_restock,
            "review_progress": self._review_progress,
            "record_seller_insight": self._record_seller_insight,
            "save_action_plan": self._save_action_plan,
            "take_action": self._take_action,
            "schedule_follow_up": self._schedule_follow_up,
            "end_call_with_summary": self._end_call_with_summary,
        }

    @staticmethod
    def label(name: str, args: dict[str, Any] | None = None) -> str:
        """Human-readable status shown in the UI while a tool runs."""
        args = args or {}
        if name == "get_account_details":
            return f"Checking {args.get('area', 'account')} details"
        if name == "take_action":
            return ACTIONS.get(str(args.get("action")), "Taking action")
        return {
            "analyze_sales_drop": "Analysing your sales data",
            "plan_restock": "Planning the restock order",
            "review_progress": "Reviewing last week's progress",
            "record_seller_insight": "Noting what you said",
            "save_action_plan": "Saving your action plan",
            "schedule_follow_up": "Booking a follow-up",
            "end_call_with_summary": "Writing the call summary",
        }.get(name, name)

    def execute(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        args = dict(args or {})
        handler = self._handlers.get(name)
        if handler is None:
            result: dict[str, Any] = {"error": f"Unknown tool '{name}'."}
        else:
            try:
                result = handler(args)
            except ToolArgumentError as exc:
                result = {"error": f"Invalid arguments: {exc}. Fix them and try again."}
        self.case.log_activity(name, self.label(name, args), args, ok="error" not in result)
        return result

    # --- insight tools ------------------------------------------------------------------

    def _analyze_sales_drop(self, _: dict[str, Any]) -> dict[str, Any]:
        analysis = diagnostics.analyze_sales_drop(self.account)
        self.case.diagnosis = {
            "summary": analysis["summary"],
            "root_cause": analysis["root_cause"],
            "drivers": analysis["drivers"],
            "sales_bridge": analysis["sales_bridge"],
            "out_of_stock_bestsellers": analysis["out_of_stock_bestsellers"],
            "running_low": analysis["running_low"],
            "early_warnings": analysis["early_warnings"],
        }
        # The UI renders the bridge; the model doesn't need it.
        return {k: v for k, v in analysis.items() if k != "sales_bridge"}

    def _get_account_details(self, args: dict[str, Any]) -> dict[str, Any]:
        area = _choice(args, "area", diagnostics.DETAIL_AREAS)
        return diagnostics.account_details(area, self.account)

    def _plan_restock(self, args: dict[str, Any]) -> dict[str, Any]:
        budget = _optional_int(args, "budget_inr", 1_000, 10_000_000)
        lead_time = _optional_int(args, "supplier_lead_time_days", 1, 90)
        if lead_time:
            self._lead_time_days = lead_time
        plan = planning.restock_plan(budget_inr=budget, lead_time_days=lead_time, account=self.account)
        self.case.restock_plan = plan
        return plan

    def _review_progress(self, _: dict[str, Any]) -> dict[str, Any]:
        result = progress.review_progress(self.previous_case, self.account)
        self.case.progress = {
            k: result[k] for k in ("period", "kpis", "wins", "open_items", "new_risks", "opportunities")
        }
        return result

    # --- ownership tools ----------------------------------------------------------------

    def _record_seller_insight(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = _choice(args, "topic", INSIGHT_TOPICS)
        insight = _text(args, "insight", max_len=240)
        if not any(i["insight"].lower() == insight.lower() for i in self.case.insights):
            self.case.insights.append({"topic": topic, "insight": insight, "at": now_ist().strftime("%H:%M")})
        return {"status": "noted"}

    def _save_action_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        raw_actions = args.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ToolArgumentError("'actions' must be a non-empty list")
        actions = []
        for raw in raw_actions[:4]:
            if not isinstance(raw, dict):
                raise ToolArgumentError("each action must be an object")
            owner = _text(raw, "owner", max_len=32, required=False) or "seller"
            actions.append(
                {
                    "title": _text(raw, "title", max_len=90),
                    "details": _text(raw, "details", max_len=360, required=False),
                    "expected_impact": _text(raw, "expected_impact", max_len=200, required=False),
                    "owner": owner if owner in OWNERS else "seller",
                    "timeline": _text(raw, "timeline", max_len=60, required=False),
                }
            )
        self.case.action_plan = actions
        self.case.kpi_targets = _str_list(args, "kpi_targets", max_items=4, max_len=160)
        return {
            "status": "saved",
            "count": len(actions),
            "next": "Explain each action in one short sentence, then offer what you can do for them right now.",
        }

    def _take_action(self, args: dict[str, Any]) -> dict[str, Any]:
        action = _choice(args, "action", tuple(ACTIONS))
        details = _text(args, "details", max_len=300, required=False)
        if args.get("seller_confirmed") is not True:
            return {"error": "Not executed: ask the seller for explicit permission first, then retry."}
        # Idempotency: a repeated request for the same action must not execute twice.
        for done in self.case.actions_taken:
            if done["action"] == action and action != "raise_support_ticket":
                return {
                    "status": "already_done",
                    "reference_id": done["reference_id"],
                    "confirmation": done["confirmation"],
                    "note": "This was already done earlier in the call; don't repeat it to the seller.",
                }
        ref = new_reference("SD")
        confirmation = self._confirmation_for(action, details)
        self.case.actions_taken.append(
            {
                "action": action,
                "label": ACTIONS[action],
                "details": details,
                "confirmation": confirmation,
                "reference_id": ref,
                "status": "done" if action != "create_sponsored_ads_draft" else "awaiting seller approval",
                "at": now_ist().strftime("%H:%M"),
            }
        )
        return {"status": "done", "reference_id": ref, "confirmation": confirmation}

    def _days_until_nominations_close(self) -> int:
        """On the follow-up call a week has passed since the first call."""
        elapsed = progress.DAYS_SINCE_FIRST_CALL if self.case.mode == "followup" else 0
        return max(0, self.account.upcoming_event.nomination_closes_in_days - elapsed)

    def _confirmation_for(self, action: str, details: str) -> str:
        event = self.account.upcoming_event
        n_top = len(self.account.top_skus)
        plan = self.case.restock_plan or planning.restock_plan(
            lead_time_days=self._lead_time_days, account=self.account
        )
        points = [i for i in plan["items"] if i.get("reorder_point_units")][:2]
        examples = " and ".join(f"{i['product'].split(' (')[0]} at {i['reorder_point_units']} units" for i in points)
        return {
            "set_low_stock_alerts": (
                f"Low-stock alerts are on for your top {n_top} products, set at each product's reorder point "
                f"(for example {examples}), so you reorder before the supplier lead time runs out. Alerts come on "
                "WhatsApp."
            ),
            "pause_unavailable_listings": (
                "Listings you can't fulfil right now are paused, so no new orders will need cancelling. They resume "
                "automatically when you update stock."
            ),
            "nominate_for_sale_event": (
                f"Nominated for {event.name}. The nomination is confirmed once each product has "
                f"{event.min_units}+ units in stock; nominations close in {self._days_until_nominations_close()} days."
            ),
            "create_sponsored_ads_draft": (
                "A 7-day sponsored-listing campaign is drafted for your restocked bestsellers. Nothing is spent "
                "until you approve it in the Seller Panel."
            ),
            "send_restock_priority_list": (
                "The restock order you agreed, with units, cost and reorder points per product, has been sent to "
                "your registered WhatsApp number to forward to your supplier."
            ),
            "raise_support_ticket": (
                "Ticket raised with the Snapdeal seller-support team; expect an update within 24 hours."
            ),
            "request_human_kam_callback": "Your human account manager will call you back within one working day.",
        }[action] + (
            f" ({details})" if details and action in {"raise_support_ticket", "send_restock_priority_list"} else ""
        )

    def _schedule_follow_up(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("seller_agreed") is not True:
            return {"error": "Not scheduled: offer the follow-up, wait for the seller's yes, then retry."}
        days = _int_in(args, "days_from_now", 1, 30)
        agenda = _text(args, "agenda", max_len=200, required=False) or "Review progress on the action plan"
        when = (now_ist() + timedelta(days=days)).replace(hour=11, minute=0, second=0, microsecond=0)
        if when.weekday() == 6:  # Sunday -> Monday
            when += timedelta(days=1)
        when_text = when.strftime("%A, %d %b %Y at 11:00 AM IST")
        if self.case.follow_up:  # reschedule instead of double-booking
            ref = self.case.follow_up["reference_id"]
            status = "rescheduled" if self.case.follow_up["when"] != when_text else "already_scheduled"
        else:
            ref, status = new_reference("FUP"), "scheduled"
        self.case.follow_up = {"when": when_text, "agenda": agenda, "reference_id": ref}
        return {"status": status, "when": when_text, "reference_id": ref}

    def _end_call_with_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        already_saved = self.case.summary is not None
        self.case.summary = {
            "key_issues": _str_list(args, "key_issues"),
            "recommendations": _str_list(args, "recommendations"),
            "next_steps": _str_list(args, "next_steps"),
            "sent_via": "WhatsApp (simulated)",
            "at": now_ist().strftime("%H:%M"),
        }
        self.case.call_ending = True
        if already_saved:
            return {"status": "updated", "next": "The summary was already sent. Just say goodbye briefly."}
        return {
            "status": "saved_and_sent",
            "next": "Now give a brief spoken summary (key issue, actions, next steps) and a warm goodbye.",
        }
