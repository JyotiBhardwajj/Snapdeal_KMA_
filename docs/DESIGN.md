# Design notes: how Disha works and why

This document explains the reasoning behind the build: the decisions, the alternatives I considered, how quality
is measured, and what would change for production.

## 1. Framing the problem

A good Key Account Manager doesn't just answer questions. They:

1. **Know the account before the call.** They come with data, not questions they could have answered themselves.
2. **Diagnose.** They separate the root cause from its symptoms and size the impact in rupees.
3. **Listen.** They ask a few targeted questions to confirm or reject hypotheses, because the seller knows things
   the data doesn't (a supplier delay, a cash crunch).
4. **Decide.** They agree on 2–3 actions that are specific, quantified and prioritised.
5. **Act.** They do what they can themselves, with permission.
6. **Follow through.** They come back, measure progress against targets and push the next step.

Disha implements every step. Steps 1–2 use a deterministic analytics engine, step 3 is the voice conversation,
step 4 uses the planner and the action plan, step 5 uses consent-gated tools, and step 6 is the 7-day follow-up
call. That last one is what turns "a bot that answers" into "an agent that owns the problem".

## 2. Architecture decisions

| Decision | Alternatives considered | Why this choice |
|---|---|---|
| **Speech-to-speech model** (Gemini Live, native audio) | STT → LLM → TTS cascade (e.g. Speech-to-Text + Gemini + Cloud TTS, or ElevenLabs) | One model hop gives lower latency (~2 s median measured end to end), natural prosody, built-in barge-in and voice activity detection, and Hindi/Hinglish code-switching without language detection glue. The trade-off is less control over voice timbre and accent; the built-in transcription covers captions and logs. |
| **Raw Live API plus my own bridge** | Agent frameworks (ADK, Pipecat, LiveKit Agents) | The tool loop, consent logic and UI events stay explicit and easy to explain. For production telephony I'd adopt LiveKit or Pipecat for media handling and keep the same tools and engine. |
| **Server-side WebSocket bridge** | Browser talks to Gemini directly with ephemeral tokens | Tools run next to the seller data, credentials never reach the browser, and every step can be mirrored to the UI and logs. It costs one extra network hop (a few tens of ms). |
| **Deterministic diagnostics engine** | Let the LLM analyse the raw numbers | Arithmetic and attribution have to be exact and auditable. The LLM only narrates numbers it receives from tools, and the prompt forbids inventing any. Unit tests pin the math to the brief. |
| **Few, coarse tools with rich results** | Many small tools | Each round trip adds latency in a voice call. One `analyze_sales_drop` call returns the metrics, verdicts, impact, questions to ask and ranked actions, plus `spoken_numbers` and `how_to_use` hints that steer phrasing. |
| **Case file as shared state** | Chat history only | A structured record (diagnosis, seller inputs, plan, actions, follow-up, summary) drives the UI and the summary download, and seeds the follow-up call. It's the KAM's CRM record. |
| **Vanilla JS with AudioWorklets** | React/Next.js | No build step, small payload, and full control of the real-time audio path (16 kHz capture, 24 kHz gap-free playback, instant flush on barge-in). |

## 3. Making the agent trustworthy

- **Grounding.** All numbers come from tools. `spoken_numbers` gives the exact phrasing ("about a third, from two
  lakh to one point three five lakh"). Arguments that appear on screen use digits.
- **Consent.** `take_action` requires `seller_confirmed=true`, and the prompt treats every offer as a question:
  ask, stop, then act in a later turn.
- **Idempotency.** Repeating an action returns `already_done` with the original reference ID. Follow-ups are
  rescheduled, never double-booked. This matters because live models sometimes retry tool calls.
- **Validation.** Bad arguments go back to the model as an error ("Invalid arguments: …") instead of crashing the
  call.
- **Untrusted input.** The previous case that the browser sends for follow-up calls is re-validated server-side:
  only known fields are kept, with length limits.
- **Security.** The WebSocket only accepts connections from the app's own origin, there's a strict CSP, model text
  is never rendered as HTML, the runtime uses a least-privilege service account, and calls are capped in length and
  concurrency. Audio is never stored.

## 4. Business logic worth calling out

- **Sales bridge.** The ₹65,000 drop splits into stock-outs (₹56,000), fewer orders on in-stock products
  (₹9,000, the visibility knock-on) and price (₹0). Every rupee is attributed.
- **Verdicts.** Each hypothesis from the brief (pricing, inventory, cancellations, visibility) gets a verdict
  backed by evidence. Pricing is explicitly ruled out, which is just as useful to a seller as the root cause.
- **Restock planner.** It turns "restock your bestsellers" into a purchase order: units, cost, monthly sales
  brought back and reorder points (daily demand × (lead time + safety days)). It's budget-aware: with ₹25,000 it
  buys the most sales per rupee first and defers the rest to phase 2.
- **Early warnings.** These are problems the seller didn't ask about: coffee mugs about 9 days from running out,
  a sale nomination deadline, and stale out-of-stock listings.
- **Follow-up simulation.** The week-later metrics depend on what was actually agreed on the first call, so the
  closed loop isn't scripted.

## 5. How quality is measured

| Layer | What it checks |
|---|---|
| Unit tests (`tests/`) | Analytics reconcile with the brief; planner math; follow-up simulation; tool validation, consent and idempotency; the WebSocket bridge with a fake Live session |
| Voice E2E (`scripts/e2e_voice_test.py`) | A full call with synthesised seller **speech**, through the real WebSocket and audio path. Reports latency per turn. |
| Browser E2E (`scripts/browser_e2e.py`) | The real UI in headless Chrome with a synthetic microphone, including the 7-day follow-up flow |
| Conversation evals (`evals/`) | 10 simulated seller personas against the production agent, scored by an LLM judge on 8 criteria plus hard checks on tool calls |
| Model A/B | The same scripted call on two Live models. `gemini-3.8-live` was about 2x faster with no duplicate tool calls. |

The evaluation suite was the most useful tool during development. Every prompt or tool change was checked against
the full persona set. That's how I caught issues such as greeting turns that jumped straight into the diagnosis,
follow-ups booked before the seller agreed, and plans without quantities. See
[evals/results/REPORT.md](../evals/results/REPORT.md).

## 6. Path to production

- **Channels:** connect a phone number (Exotel, Twilio or SIP) to the same bridge, and use WhatsApp for summaries
  and nudges.
- **Data and actions:** replace `seller_data.py` with Seller Panel and analytics APIs, and turn the simulated
  actions into real API calls with the same consent and idempotency contract.
- **Memory:** persist case files (e.g. Firestore) keyed by seller, so every call starts from the last one and
  outcomes are tracked.
- **Proactive triggers:** a scheduled anomaly-detection job (stock-out spikes, cancellation spikes) that starts
  outbound calls. This is the "Disha calls proactively" mode, run at scale.
- **Human in the loop:** escalation to human KAMs with the case file attached, plus QA sampling of transcripts.
- **Compliance:** recording consent at the start of calls, retention limits, and India's DPDP Act requirements for
  personal data.
- **Success metrics:** recovered GMV per seller, action adoption rate, follow-up completion, cancellation-rate
  reduction, escalation rate, CSAT, plus latency and cost per call.

## 7. Lessons from building it

- **The hard part of a voice agent is turn-taking, not knowledge.** Most of the bugs were about timing:
  - Echo from speakers made Disha interrupt herself, so I added an echo guard.
  - `gemini-3.8-live` streams audio at real-time pace, so a pause mid-turn (for example while a tool runs)
    looked like the end of her turn. The UI now treats the turn as hers until `turn_complete` arrives.
  - When to hang up: never right after a question, and cancel the hang-up if the seller keeps talking.
- **If the prompt contains the numbers, the model skips the tools.** With the brief's figures written into the
  call flow, the Hindi run answered from memory and never ran the diagnosis. The prompt now holds no metric
  values at all.
- **Consent has to be enforced in code, not just in the prompt.** The model sometimes booked the follow-up in the
  same breath as offering it. `schedule_follow_up` now rejects calls without `seller_agreed=true`, and the model
  recovers by asking.
- **Speaking between tool calls makes the model repeat itself.** A turn of speak → tool → speak again restates
  the plan. "Tools first, then speak once" fixed most of it.
- **Evals are noisy, so repeat them.** The same prompt can score 3.0 on one run and 4.9 on the next. The final
  report averages independent runs per persona and shows the range.
- **Make test harnesses fail loudly.** Two "model failures" were really harness bugs: a silent fallback that
  ended calls early, and a synthesised seller line that came back as empty audio. Both now raise errors instead of
  quietly skewing the results.
