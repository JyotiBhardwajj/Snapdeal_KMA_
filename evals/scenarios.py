"""Seller personas for the conversation evaluation suite.

Each scenario is a different kind of seller: cooperative, cash-strapped, set on cutting prices, angry,
speaking Hinglish, wanting a human, blaming the courier, going off-topic, busy, or on the follow-up call.
`facts` is what the simulated seller knows and reveals when relevant; `expectation` tells the judge what a
great Virtual KAM does in this situation; `required_tools` are hard checks on the tool log.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolExpectation:
    tool: str
    arg: str | None = None
    value: str | None = None  # substring match on str(args[arg]); None = only require the arg to be present

    def matches(self, call: dict) -> bool:
        if call["tool"] != self.tool:
            return False
        if self.arg is None:
            return True
        if self.arg not in call["args"]:
            return False
        return self.value is None or self.value in str(call["args"][self.arg])

    def describe(self) -> str:
        if self.arg is None:
            return self.tool
        return f"{self.tool}({self.arg}{'=' + self.value if self.value else ''})"


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    mode: str  # inbound | outbound | followup
    language: str  # en | hi
    facts: str
    behaviour: str
    expectation: str
    required_tools: tuple[ToolExpectation, ...] = field(default_factory=tuple)


DIAGNOSE = ToolExpectation("analyze_sales_drop")
SUMMARY = ToolExpectation("end_call_with_summary")

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="cooperative",
        title="Cooperative seller, supplier delay",
        mode="inbound",
        language="en",
        facts=(
            "Your main supplier in Delhi delayed your stock by almost three weeks because of the festive rush. You "
            "update stock on Snapdeal manually, about once a week, so some orders came in for items you didn't have "
            "and you had to cancel them. You can restock within a week and money is not a problem."
        ),
        behaviour="Polite and cooperative. Answer questions directly. Agree to sensible offers, including a follow-up.",
        expectation="Full flow: diagnosis with numbers, 2-3 questions, tailored plan with quantities, actions with "
        "consent, follow-up booked, summary.",
        required_tools=(DIAGNOSE, ToolExpectation("save_action_plan"), ToolExpectation("plan_restock"), SUMMARY),
    ),
    Scenario(
        id="cash_crunch",
        title="Can't afford a full restock",
        mode="inbound",
        language="en",
        facts=(
            "Cash is tight after the festive season. You can spend only about 25,000 rupees on restocking right now. "
            "Your supplier is fine; you simply couldn't pay for new stock in time."
        ),
        behaviour="Worried. When restocking comes up, say you can't afford to restock everything and ask what to do.",
        expectation="Uses plan_restock with the 25,000 budget, prioritises the products with most sales per rupee, "
        "and proposes a phased plan instead of generic advice.",
        required_tools=(DIAGNOSE, ToolExpectation("plan_restock", "budget_inr"), SUMMARY),
    ),
    Scenario(
        id="price_cutter",
        title="Wants to cut prices",
        mode="inbound",
        language="en",
        facts=(
            "You believe competitors are cheaper and want to cut all prices by 15 percent to win sales back. The "
            "stock-outs happened because you forgot to reorder in time."
        ),
        behaviour="Push the price-cut idea early and once more later. Accept good reasoning backed by numbers.",
        expectation="Explains with data that prices are competitive (within 3%) and unchanged, so a blanket cut "
        "would hurt margins without fixing availability; redirects to restocking; at most a targeted promotion "
        "after restocking.",
        required_tools=(DIAGNOSE, SUMMARY),
    ),
    Scenario(
        id="angry",
        title="Angry, blames Snapdeal",
        mode="inbound",
        language="en",
        facts=(
            "You think Snapdeal's algorithm is hiding your products on purpose. In reality your supplier was late and "
            "several bestsellers went out of stock."
        ),
        behaviour=(
            "Start angry: 'Snapdeal is killing my business!' Be short-tempered for the first two turns. Calm down "
            "only if Disha is empathetic and gives concrete, useful answers."
        ),
        expectation="Acknowledges the frustration without arguing or over-apologising, explains the real cause "
        "calmly with data (including how stock-outs reduce visibility), and turns it into a concrete plan.",
        required_tools=(DIAGNOSE, SUMMARY),
    ),
    Scenario(
        id="hinglish",
        title="Speaks Hinglish",
        mode="inbound",
        language="hi",
        facts=(
            "Your Delhi supplier was late by about three weeks because of the festive rush. You update stock manually "
            "once a week, so you had to cancel some orders."
        ),
        behaviour="Speak only Hinglish (Hindi in Roman script mixed with English business words). Cooperative.",
        expectation="Replies in natural Hindi/Hinglish throughout with correct numbers, and completes the full flow.",
        required_tools=(DIAGNOSE, SUMMARY),
    ),
    Scenario(
        id="wants_human",
        title="Asks for a human manager",
        mode="inbound",
        language="en",
        facts="You don't trust AI and want to speak to your human account manager. Your sales dropped this month.",
        behaviour=(
            "Ask for a human in your first or second message. If Disha respects that and offers a callback, accept "
            "it, and listen to one key finding if she offers. Don't agree to a long conversation."
        ),
        expectation="Respects the request, offers a human callback (executed only after consent), optionally shares "
        "the single most important finding briefly, and doesn't force the full flow.",
        required_tools=(ToolExpectation("take_action", "action", "request_human_kam_callback"),),
    ),
    Scenario(
        id="blames_courier",
        title="Insists the courier is the problem",
        mode="inbound",
        language="en",
        facts=(
            "You believe cancellations are mainly because the courier picks up late. You did run out of a few "
            "products, but you think that's minor."
        ),
        behaviour="Insist on the courier explanation twice. Accept the data if Disha shows it respectfully.",
        expectation="Acknowledges the courier concern and raises a ticket for it, but shows with data that most "
        "cancellations are for unavailable items (24 of 38) and late dispatch is small (5), then focuses on stock.",
        required_tools=(DIAGNOSE, ToolExpectation("take_action", "action", "raise_support_ticket")),
    ),
    Scenario(
        id="off_topic",
        title="Drifts off-topic",
        mode="inbound",
        language="en",
        facts=(
            "Your supplier was late, so bestsellers went out of stock. You are also stressed about your GST filing "
            "and curious about selling on another marketplace."
        ),
        behaviour="Mid-call, ask for help with your GST filing. Later ask whether you should also sell on Amazon.",
        expectation="Politely says GST and other platforms are outside this call, without lecturing, and steers back "
        "to the sales problem; still completes a plan.",
        required_tools=(DIAGNOSE, SUMMARY),
    ),
    Scenario(
        id="busy_outbound",
        title="Proactive call to a busy seller",
        mode="outbound",
        language="en",
        facts="You are at your warehouse and busy. You had noticed sales were down but hadn't looked into it.",
        behaviour=(
            "When Disha calls, say you're busy and ask her to be quick. If she gives a crisp summary, engage for a "
            "couple of turns, then ask to wrap up."
        ),
        expectation="Opens with the data-driven reason for the call, respects the time pressure with a short version "
        "or a callback offer, still lands one or two concrete actions, and closes quickly.",
        required_tools=(DIAGNOSE,),
    ),
    Scenario(
        id="follow_up",
        title="7-day follow-up call",
        mode="followup",
        language="en",
        facts=(
            "Since last week you restocked the water bottles, towels and glass jars. The spice rack supplier shipped "
            "only half the order. You haven't looked at the coffee mugs. You'd like more sales from the upcoming sale."
        ),
        behaviour="Friendly. Answer questions about progress. Agree to sensible next steps.",
        expectation="Calls review_progress first, reminds what was agreed, leads with wins (with numbers), covers "
        "what's behind, proactively raises the mug stock risk and the sale nomination deadline, and agrees next "
        "actions with consent.",
        required_tools=(ToolExpectation("review_progress"), SUMMARY),
    ),
)
