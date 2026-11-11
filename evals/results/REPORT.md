# Conversation evaluation report

Generated 2026-11-10 11:33 UTC · Agent: `gemini-3.8-live` (Gemini Live, native audio) · Simulated seller: `gemini-3.8-flash` · Judge: `gemini-2.5-pro` · 2 independent run(s) per scenario

Each run is a full call between Disha (production prompt, tools and Live model) and a simulated seller persona. Scores are from an LLM judge (1–5) that sees the account's ground truth, the transcript with tool calls, and the final case file. Hard checks verify that the required tool calls were made. Click a run number to read the full transcript and the judge's reasoning.

**Overall average: 4.72 / 5** across 20 calls · hard checks passed in 19/20 calls.

| Scenario | Runs | Understanding | Grounding | Diagnosis | Questions | Recommendations | Ownership | Voice Style | Scenario Handling | Avg (range) | Words/turn | Hard checks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cooperative seller, supplier delay | [1](transcripts/cooperative-1.md) [2](transcripts/cooperative-2.md) | 5.0 | 5.0 | 5.0 | 5.0 | 4.0 | 5.0 | 5.0 | 4.5 | **4.81** (4.75–4.88) | 44 | 2/2 |
| Can't afford a full restock | [1](transcripts/cash_crunch-1.md) [2](transcripts/cash_crunch-2.md) | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | **5.00** (5.00–5.00) | 43 | 2/2 |
| Wants to cut prices | [1](transcripts/price_cutter-1.md) [2](transcripts/price_cutter-2.md) | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | **5.00** (5.00–5.00) | 47 | 2/2 |
| Angry, blames Snapdeal | [1](transcripts/angry-1.md) [2](transcripts/angry-2.md) | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | **5.00** (5.00–5.00) | 46 | 2/2 |
| Speaks Hinglish | [1](transcripts/hinglish-1.md) [2](transcripts/hinglish-2.md) | 4.5 | 3.0 | 5.0 | 5.0 | 3.5 | 4.5 | 4.5 | 4.5 | **4.31** (3.75–4.88) | 46 | 2/2 |
| Asks for a human manager | [1](transcripts/wants_human-1.md) [2](transcripts/wants_human-2.md) | 5.0 | 5.0 | 5.0 | 3.5 | 4.0 | 5.0 | 4.0 | 4.5 | **4.50** (4.12–4.88) | 42 | 2/2 |
| Insists the courier is the problem | [1](transcripts/blames_courier-1.md) [2](transcripts/blames_courier-2.md) | 5.0 | 5.0 | 4.0 | 4.5 | 5.0 | 5.0 | 5.0 | 3.5 | **4.62** (4.25–5.00) | 48 | 1/2 |
| Drifts off-topic | [1](transcripts/off_topic-1.md) [2](transcripts/off_topic-2.md) | 5.0 | 3.5 | 5.0 | 5.0 | 5.0 | 5.0 | 4.0 | 5.0 | **4.69** (4.38–5.00) | 61 | 2/2 |
| Proactive call to a busy seller | [1](transcripts/busy_outbound-1.md) [2](transcripts/busy_outbound-2.md) | 4.0 | 5.0 | 5.0 | 4.0 | 4.5 | 3.5 | 4.5 | 4.0 | **4.31** (3.62–5.00) | 44 | 2/2 |
| 7-day follow-up call | [1](transcripts/follow_up-1.md) [2](transcripts/follow_up-2.md) | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 4.5 | **4.94** (4.88–5.00) | 34 | 2/2 |
| **Average** | | **4.8** | **4.7** | **4.9** | **4.7** | **4.6** | **4.8** | **4.7** | **4.5** | **4.72** | | |

## Critical issues flagged by the judge

- **Speaks Hinglish** (run 1): The restock recommendation was critically flawed: it presented a partial list of products (2 items) but attached the cost and recovery figures for the full plan, making the proposal highly misleading.
- **Drifts off-topic** (run 2): Made a significant grounding error by stating the wrong stock level for Ceramic Coffee Mugs (said 18 units were left, but it was 6), which could cause the seller to misjudge the urgency.
- **Proactive call to a busy seller** (run 2): Scheduling a follow-up call without the seller's explicit consent.
