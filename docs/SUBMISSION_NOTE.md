# Disha: AI Virtual KAM for Snapdeal sellers (submission note)

**Demo:** `<demo URL>` · **Code:** `<GitHub URL>` · **Recording:** `<video URL>`

## What I built
Disha is a voice-first Virtual Key Account Manager that **takes ownership** of a seller's problem instead of just
answering questions. A seller says *"my sales dropped"*, and Disha:

1. diagnoses the account from data;
2. asks 2–3 targeted questions;
3. turns the fix into a costed restock order, fitted to the seller's budget if cash is tight;
4. flags risks the seller didn't ask about;
5. acts on their behalf, only after they say yes;
6. books a follow-up and closes with a summary.

"Fast-forward 7 days" plays the **follow-up call**: Disha reviews progress against the targets she set and agrees
the next steps. A live case file shows everything she learns and does.

## AI model and voice technology
- **`gemini-3.8-live` via the Gemini Live API (Vertex AI).** It's a native-audio, speech-to-speech model: it hears
  raw audio and answers in audio in one hop. It provides voice activity detection, barge-in (you can interrupt
  her) and function calling during the conversation. In an A/B test against
  `gemini-live-2.5-flash-native-audio` it had about half the latency (median ~2 s from the end of the seller's
  speech to Disha's first audio) and no duplicate tool calls.
- **No separate STT/TTS services.** The same model listens and speaks (voice "Kore"). It handles English, Hindi
  and Hinglish. Captions come from the Live API's built-in transcription.
- **Browser audio:** AudioWorklets send 16 kHz PCM up and play 24 kHz PCM down. Echo cancellation is on, plus an
  echo guard so laptop speakers don't trigger false interruptions.

## Workflow
Browser mic → WebSocket → FastAPI bridge (Cloud Run) → Gemini Live. When the model calls a tool, the server runs
it and the case file updates live.
- `analyze_sales_drop`: a **deterministic** engine (not the LLM) does the math. The ₹65,000 (32.5%) drop is all
  volume, since the average price is flat. Stock-outs (5 → 18) explain ₹56,000 of it. Cancellations (8% → 14%) are
  mostly orders for stock the seller didn't have. Lower visibility is a knock-on effect, and pricing is ruled out.
- `plan_restock`: units, cost, monthly sales recovered and reorder points (which include the supplier lead time),
  fitted to a budget if needed. For example, with ₹25,000: 18 mug sets and 62 bottle packs bring back about
  ₹43,000 a month.
- `record_seller_insight` and `save_action_plan` personalise the plan. `take_action` and `schedule_follow_up`
  require explicit consent and can't run twice. `end_call_with_summary` closes the call. `review_progress` drives
  the 7-day follow-up.

## How I made it reliable
- **The LLM handles the conversation, code handles the math.** Disha only quotes numbers from tools, and unit
  tests pin those numbers to the brief.
- **Evaluation suite:** 10 simulated seller personas talk to the production agent and an LLM judge scores 8
  criteria. The personas cover a cooperative seller, a cash crunch, a seller set on price cuts, an angry seller,
  Hinglish, a request for a human, blaming the courier, off-topic questions, a busy seller, and the follow-up call.
  Iterating on prompts and tools with it raised the average from 4.41 to 4.72 / 5, averaged over two independent
  runs per persona (see `evals/results/REPORT.md`).
- **Also tested:** 78 unit tests, a voice end-to-end test with synthesised speech, and a headless-Chrome UI test
  with a synthetic microphone.

## Assumptions (labelled in the app)
I used the brief's five metrics exactly. To make the conversation specific, I added a fictional seller, SKU-level
stock (top 8 products plus a long tail), cancellation reasons, product views, a competitor price index, a
fictional sale, and a unit cost of ₹300. All of these add up exactly to the brief's totals, and tests enforce
that. The follow-up call's week-later metrics are simulated from what was agreed on the first call.
