#!/usr/bin/env python3
"""Conversation evaluation suite: simulated sellers talk to the real Disha agent, an LLM judge scores the calls.

    python -m evals.run_evals                     # all scenarios
    python -m evals.run_evals cash_crunch angry   # a subset

Disha runs exactly as in production: same system prompt, tools, executor and Live (native-audio) model. The only
difference is that the seller's turns are sent as text instead of audio, so many varied conversations can run in
minutes. The audio path is covered separately by scripts/e2e_voice_test.py and scripts/browser_e2e.py.

Outputs evals/results/REPORT.md and one transcript per scenario under evals/results/transcripts/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import diagnostics  # noqa: E402
from app.case_file import CaseFile  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live_session import build_live_config  # noqa: E402
from app.planning import restock_plan  # noqa: E402
from app.progress import DEFAULT_PREVIOUS_CASE, review_progress  # noqa: E402
from app.prompts import kickoff_prompt  # noqa: E402
from app.tools import ToolExecutor  # noqa: E402
from evals.scenarios import SCENARIOS, Scenario  # noqa: E402

RESULTS_DIR = ROOT / "evals" / "results"
MAX_SELLER_TURNS = 12
SELLER_MODEL = os.getenv("EVAL_SELLER_MODEL", "gemini-3.8-flash")
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gemini-2.5-pro")
TEXT_LOCATION = os.getenv("EVAL_TEXT_LOCATION", "global")
CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "4"))

CRITERIA = (
    ("understanding", "Understood the seller's concern and the scenario-specific situation"),
    ("grounding", "Every figure matches the ground truth or tool output; nothing invented"),
    ("diagnosis", "Correct root cause and reasoning (or correct progress assessment on a follow-up)"),
    ("questions", "Relevant follow-up questions, one per turn, adapted to the answers"),
    ("recommendations", "2-3 specific, prioritised, quantified, practical actions tailored to the seller"),
    ("ownership", "Drove next steps: concrete actions executed only with consent, follow-up booked where useful"),
    ("voice_style", "Concise, natural, warm turns suited to voice, in the right language"),
    ("scenario_handling", "Handled this scenario's specific challenge well"),
)


class Criterion(BaseModel):
    score: int
    reason: str


class Verdict(BaseModel):
    understanding: Criterion
    grounding: Criterion
    diagnosis: Criterion
    questions: Criterion
    recommendations: Criterion
    ownership: Criterion
    voice_style: Criterion
    scenario_handling: Criterion
    critical_issues: list[str]
    overall_comment: str


SELLER_PROMPT = """\
You are role-playing a Snapdeal seller on a phone call with Disha, Snapdeal's AI account manager.
You are Rajesh Gupta, owner of Gupta Home Essentials in Jaipur (home and kitchen products).
Your sales dropped a lot this month. You don't know exact numbers about your account.

What you know (reveal only when relevant or asked): {facts}
How you behave on this call: {behaviour}

Rules:
- Reply with ONLY your next spoken words: 1-2 short, natural sentences. No stage directions, no quotes.
- {language_rule}
- Stay in character. Don't invent detailed numbers about your account.
- If the call has clearly ended (Disha said goodbye, or you have nothing more to say after her summary), reply \
exactly: [END]

The call so far:
{conversation}
YOU:"""

JUDGE_PROMPT = """\
You are a demanding evaluator of a voice AI "Virtual Key Account Manager" (Disha) for Snapdeal sellers. Score how \
well Disha handled this call. The seller is simulated.

## Ground truth (what the seller's account data shows)
{ground_truth}

## Scenario: {title}
Seller situation: {facts}
Seller behaviour: {behaviour}
What a great KAM does here: {expectation}

## Transcript (spoken turns; Disha's tool calls are shown in brackets)
{transcript}

## Final case file (what Disha saved)
{case}

## How to score
Score each criterion from 1 (poor) to 5 (excellent) with one short, specific reason:
{criteria}
Be strict: 5 means you would not change anything. Penalise invented or wrong numbers, more than one question in a \
turn, long-winded voice turns, actions taken without the seller's explicit yes, wrong language, and ignoring what \
the seller said. Only take_action and schedule_follow_up tool calls are actions; recommendations in a plan or summary \
are not actions. Figures returned by tools (including plan_restock costs and quantities) are grounded. List any \
critical issues (empty list if none)."""


def _ground_truth(sc: Scenario) -> str:
    if sc.mode == "followup":
        p = review_progress(DEFAULT_PREVIOUS_CASE)
        kpis = "; ".join(
            f"{k['metric']}: before {k['before']}, target {k['target']}, last 7 days {k['now']} ({k['status']})"
            for k in p["kpis"]
        )
        return (
            f"Follow-up call one week after the first call. KPIs: {kpis}. Wins: {p['wins']}. Open: {p['open_items']}. "
            f"New risks: {p['new_risks']}. Opportunities: {p['opportunities']}. "
            f"Agreed last time: {p['agreed_last_time']}. Suggested next actions: {p['suggested_next_actions']}. "
            f"Restock plan: {restock_plan()['spoken_hint']} (coffee mugs: 18 sets, ₹5,400)."
        )
    a = diagnostics.analyze_sales_drop()
    drivers = "; ".join(
        f"{d['label']}: {d['verdict']} ({d['headline']}; monthly impact ₹{d['monthly_impact_inr']:,})"
        for d in a["drivers"]
    )
    actions = "; ".join(f"{c['title']}: {c['details']} Impact: {c['expected_impact']}" for c in a["candidate_actions"])
    canc = diagnostics.account_details("cancellations")["this_month"]
    plan = restock_plan()
    items = "; ".join(
        f"{i['product']}: order {i['order_units']} (on hand {i['on_hand']}), ₹{i['cost_inr']:,}, "
        f"₹{i['monthly_sales_inr']:,}/month"
        for i in plan["items"]
    )
    return (
        f"{a['summary']} Drivers: {drivers}. Root cause: {a['root_cause']} "
        f"Cancellations this month: {canc}. Competitor prices within ±3%. Candidate actions: {actions}. "
        f"Restock plan: {items}. {plan['summary']} With a ₹25,000 budget: "
        f"{restock_plan(budget_inr=25_000)['summary']} Early warnings: {[w['text'] for w in a['early_warnings']]}. "
        "Figures quoted from these (e.g. ₹56,000 a month from stock-outs, ₹8,100 a month from extra cancellations, "
        "₹9,000 a month from lower visibility) are grounded."
    )


async def _pump(session: Any, queue: asyncio.Queue) -> None:
    while True:
        async for message in session.receive():
            await queue.put(message)


async def _collect_turn(
    queue: asyncio.Queue, session: Any, tools: ToolExecutor, tool_log: list[dict], turn: int
) -> tuple[str, float]:
    """Collect one full Disha turn, executing tool calls, until she has finished speaking.

    Returns the transcript and the seconds of audio she produced (24 kHz PCM16), which shows whether a transcript
    that ends mid-sentence is a cut-off reply or just lagging transcription.
    """
    loop = asyncio.get_running_loop()
    parts: list[str] = []
    audio_bytes = 0
    deadline = loop.time() + 60
    finished_at: float | None = None
    while True:
        timeout = 4.0 if finished_at else max(0.1, deadline - loop.time())
        try:
            message = await asyncio.wait_for(queue.get(), timeout)
        except TimeoutError:
            break
        content = message.server_content
        if content and content.model_turn:
            audio_bytes += sum(len(p.inline_data.data) for p in content.model_turn.parts or [] if p.inline_data)
        if content and content.output_transcription and content.output_transcription.text:
            parts.append(content.output_transcription.text)
        if message.tool_call and message.tool_call.function_calls:
            responses = []
            for call in message.tool_call.function_calls:
                args = dict(call.args or {})
                result = tools.execute(call.name or "", args)
                status = "error" if "error" in result else str(result.get("status", "ok"))
                tool_log.append(
                    {"turn": turn, "tool": call.name, "args": args, "status": status, "error": result.get("error")}
                )
                responses.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
            await session.send_tool_response(function_responses=responses)
            finished_at, deadline = None, loop.time() + 45
        if content and content.turn_complete:
            finished_at = loop.time()
    return " ".join("".join(parts).split()), round(audio_bytes / 48_000, 1)


async def _seller_says(client: genai.Client, sc: Scenario, transcript: list[dict]) -> str:
    conversation = "\n".join(f"{'DISHA' if t['role'] == 'disha' else 'YOU'}: {t['text']}" for t in transcript)
    language_rule = (
        "Speak only Hinglish: Hindi written in Roman script, mixed with English business words."
        if sc.language == "hi"
        else "Speak natural Indian English."
    )
    prompt = SELLER_PROMPT.format(
        facts=sc.facts, behaviour=sc.behaviour, language_rule=language_rule, conversation=conversation
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = await client.aio.models.generate_content(
                model=SELLER_MODEL, contents=prompt, config=types.GenerateContentConfig(temperature=0.7)
            )
            text = " ".join((response.text or "").split())
            if text:
                return text
            last_error = RuntimeError("empty simulated-seller reply")
        except Exception as exc:  # transient model errors (e.g. rate limits): retry with backoff
            last_error = exc
        await asyncio.sleep(3 * (attempt + 1))
    # Fail loudly: silently ending the call would look like a short conversation and skew the scores.
    raise RuntimeError(f"Seller simulator failed: {last_error}")


async def run_conversation(sc: Scenario, live: genai.Client, text_client: genai.Client) -> dict:
    settings = get_settings()
    previous = DEFAULT_PREVIOUS_CASE if sc.mode == "followup" else None
    case = CaseFile.open(mode=sc.mode, language=sc.language, previous_case_id=(previous or {}).get("case_id"))
    tools = ToolExecutor(case, previous_case=previous)
    config = build_live_config(settings, sc.language, sc.mode, previous)
    transcript: list[dict] = []
    tool_log: list[dict] = []
    started = time.monotonic()
    async with live.aio.live.connect(model=settings.live_model, config=config) as session:
        queue: asyncio.Queue = asyncio.Queue()
        pump = asyncio.create_task(_pump(session, queue))
        try:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=kickoff_prompt(sc.mode))]), turn_complete=True
            )
            opening, seconds = await _collect_turn(queue, session, tools, tool_log, 0)
            transcript.append({"role": "disha", "text": opening, "audio_s": seconds})
            for _ in range(MAX_SELLER_TURNS):
                seller = await _seller_says(text_client, sc, transcript)
                if seller.upper().startswith("[END]"):
                    break
                transcript.append({"role": "seller", "text": seller})
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=seller)]), turn_complete=True
                )
                reply, seconds = await _collect_turn(queue, session, tools, tool_log, len(transcript))
                transcript.append({"role": "disha", "text": reply, "audio_s": seconds})
                # Mirror the app: hang up after the closing turn, unless Disha just asked something.
                if case.call_ending and not reply.rstrip().endswith("?"):
                    break
        finally:
            pump.cancel()
    return {
        "scenario": sc.id,
        "duration_s": round(time.monotonic() - started),
        "transcript": transcript,
        "tool_log": tool_log,
        "case": case.to_dict(),
    }


def _checks(sc: Scenario, run: dict) -> dict:
    calls = run["tool_log"]
    disha = [t["text"] for t in run["transcript"] if t["role"] == "disha" and t["text"]]
    body = disha[1:-1] or disha  # leave out the greeting and the closing summary
    words = [len(t.split()) for t in body] or [0]
    return {
        "required_tools_missing": [e.describe() for e in sc.required_tools if not any(e.matches(c) for c in calls)],
        "avg_words_per_turn": round(statistics.mean(words)),
        "max_words_per_turn": max(words),
        "multi_question_turns": sum(1 for t in body if t.count("?") > 1),
        "duplicate_actions": sum(1 for c in calls if c["status"] == "already_done"),
        "tool_errors": sum(1 for c in calls if c["status"] == "error"),
        "turns": len(run["transcript"]),
    }


def _transcript_text(run: dict) -> str:
    lines = []
    for index, turn in enumerate(run["transcript"]):
        tools = [
            f"[{c['tool']}({json.dumps(c['args'], ensure_ascii=False)}) -> {c['status']}]"
            for c in run["tool_log"]
            if c["turn"] == index
        ]
        who = "DISHA" if turn["role"] == "disha" else "SELLER"
        lines.append(f"{who}: {' '.join(tools) + ' ' if tools else ''}{turn['text']}")
    return "\n".join(lines)


async def judge(client: genai.Client, sc: Scenario, run: dict) -> Verdict:
    case = {
        k: run["case"].get(k)
        for k in ("insights", "action_plan", "kpi_targets", "actions_taken", "follow_up", "summary")
    }
    prompt = JUDGE_PROMPT.format(
        ground_truth=_ground_truth(sc),
        title=sc.title,
        facts=sc.facts,
        behaviour=sc.behaviour,
        expectation=sc.expectation,
        transcript=_transcript_text(run),
        case=json.dumps(case, ensure_ascii=False, indent=1),
        criteria="\n".join(f"- {key}: {desc}" for key, desc in CRITERIA),
    )
    for attempt in range(3):
        try:
            response = await client.aio.models.generate_content(
                model=JUDGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0, response_mime_type="application/json", response_schema=Verdict
                ),
            )
            verdict = (
                response.parsed if isinstance(response.parsed, Verdict) else Verdict.model_validate_json(response.text)
            )
            for key, _ in CRITERIA:
                getattr(verdict, key).score = max(1, min(5, getattr(verdict, key).score))
            return verdict
        except Exception:
            await asyncio.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Judge failed for {sc.id}")


def _average(verdict: Verdict) -> float:
    return round(statistics.mean(getattr(verdict, key).score for key, _ in CRITERIA), 2)


def _transcript_page(r: dict, run_number: int) -> str:
    sc, verdict, checks = r["scenario"], r["verdict"], r["checks"]
    return "\n".join(
        [
            f"# {sc.title} (run {run_number})",
            "",
            f"Mode: `{sc.mode}` · Language: `{sc.language}` · Duration: {r['run']['duration_s']} s · "
            f"Average judge score: **{_average(verdict):.2f} / 5**",
            "",
            f"**Seller situation:** {sc.facts}",
            "",
            f"**Seller behaviour:** {sc.behaviour}",
            "",
            f"**What a great KAM does:** {sc.expectation}",
            "",
            "## Transcript",
            "",
            *[f"> {line}\n>" for line in _transcript_text(r["run"]).splitlines()],
            "",
            "## Judge",
            "",
            "| Criterion | Score | Reason |",
            "|---|---|---|",
            *[f"| {key} | {getattr(verdict, key).score} | {getattr(verdict, key).reason} |" for key, _ in CRITERIA],
            "",
            f"**Overall:** {verdict.overall_comment}",
            "",
            f"**Critical issues:** {', '.join(verdict.critical_issues) or 'none'}",
            "",
            f"**Automated checks:** `{json.dumps(checks)}`",
            "",
        ]
    )


def write_reports(results: list[dict], settings_model: str, repeat: int) -> Path:
    transcripts = RESULTS_DIR / "transcripts"
    if transcripts.exists():
        for old in transcripts.glob("*.md"):
            old.unlink()
    transcripts.mkdir(parents=True, exist_ok=True)

    by_scenario: dict[str, list[dict]] = {}
    for r in results:
        by_scenario.setdefault(r["scenario"].id, []).append(r)

    rows, issues = [], []
    for sid, runs in by_scenario.items():
        sc = runs[0]["scenario"]
        links = []
        for n, r in enumerate(runs, start=1):
            name = f"{sid}-{n}.md"
            (transcripts / name).write_text(_transcript_page(r, n), encoding="utf-8")
            links.append(f"[{n}](transcripts/{name})")
            issues += [f"- **{sc.title}** (run {n}): {i}" for i in r["verdict"].critical_issues]
        means = [statistics.mean(getattr(r["verdict"], key).score for r in runs) for key, _ in CRITERIA]
        avgs = [_average(r["verdict"]) for r in runs]
        passed = sum(1 for r in runs if not r["checks"]["required_tools_missing"])
        spread = f" ({min(avgs):.2f}–{max(avgs):.2f})" if len(avgs) > 1 else ""
        words = round(statistics.mean(r["checks"]["avg_words_per_turn"] for r in runs))
        rows.append(
            f"| {sc.title} | {' '.join(links)} | "
            + " | ".join(f"{m:.1f}" for m in means)
            + f" | **{statistics.mean(avgs):.2f}**{spread} | {words} | {passed}/{len(runs)} |"
        )

    averages = [statistics.mean(getattr(r["verdict"], key).score for r in results) for key, _ in CRITERIA]
    overall = statistics.mean(_average(r["verdict"]) for r in results)
    hard_pass = sum(1 for r in results if not r["checks"]["required_tools_missing"])
    header = (
        "| Scenario | Runs | "
        + " | ".join(k.replace("_", " ").title() for k, _ in CRITERIA)
        + " | Avg (range) | Words/turn | Hard checks |"
    )
    report = [
        "# Conversation evaluation report",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · Agent: `{settings_model}` (Gemini Live, native audio) · "
        f"Simulated seller: `{SELLER_MODEL}` · Judge: `{JUDGE_MODEL}` · {repeat} independent run(s) per scenario",
        "",
        "Each run is a full call between Disha (production prompt, tools and Live model) and a simulated seller "
        "persona. Scores are from an LLM judge (1–5) that sees the account's ground truth, the transcript with tool "
        "calls, and the final case file. Hard checks verify that the required tool calls were made. Click a run "
        "number to read the full transcript and the judge's reasoning.",
        "",
        f"**Overall average: {overall:.2f} / 5** across {len(results)} calls · hard checks passed in "
        f"{hard_pass}/{len(results)} calls.",
        "",
        header,
        "|" + "---|" * (len(CRITERIA) + 5),
        *rows,
        "| **Average** | | " + " | ".join(f"**{a:.1f}**" for a in averages) + f" | **{overall:.2f}** | | |",
        "",
        "## Critical issues flagged by the judge",
        "",
        *(issues or ["None."]),
        "",
    ]
    path = RESULTS_DIR / "REPORT.md"
    path.write_text("\n".join(report), encoding="utf-8")
    (RESULTS_DIR / "results.json").write_text(
        json.dumps(
            [
                {"scenario": r["scenario"].id, "checks": r["checks"], "verdict": r["verdict"].model_dump(), **r["run"]}
                for r in results
            ],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", help="Scenario ids (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="Independent runs per scenario (default 1)")
    args = parser.parse_args()
    selected = [s for s in SCENARIOS if not args.scenarios or s.id in args.scenarios]
    settings = get_settings()
    live = genai.Client(vertexai=True, project=settings.google_cloud_project, location=settings.google_cloud_location)
    text = genai.Client(vertexai=True, project=settings.google_cloud_project, location=TEXT_LOCATION)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(sc: Scenario) -> dict | None:
        async with gate:
            for attempt in range(2):
                try:
                    run = await run_conversation(sc, live, text)
                    verdict = await judge(text, sc, run)
                    checks = _checks(sc, run)
                    print(
                        f"  {sc.id:16} avg {_average(verdict):.2f}  turns {checks['turns']:2}  "
                        f"missing {checks['required_tools_missing']}",
                        flush=True,
                    )
                    return {"scenario": sc, "run": run, "verdict": verdict, "checks": checks}
                except Exception as exc:
                    print(f"  {sc.id:16} attempt {attempt + 1} failed: {type(exc).__name__}: {exc}", flush=True)
            return None

    jobs = [sc for sc in selected for _ in range(max(1, args.repeat))]
    print(f"Running {len(jobs)} calls ({len(selected)} scenarios x {args.repeat}) against {settings.live_model}...")
    results = [r for r in await asyncio.gather(*(one(s) for s in jobs)) if r]
    order = {s.id: i for i, s in enumerate(SCENARIOS)}
    results.sort(key=lambda r: order[r["scenario"].id])
    if not results:
        return 1
    path = write_reports(results, settings.live_model, max(1, args.repeat))
    print(f"Report: {path.relative_to(ROOT)}")
    return 0 if len(results) == len(jobs) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
