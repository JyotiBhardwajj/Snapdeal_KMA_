# Angry, blames Snapdeal (run 2)

Mode: `inbound` · Language: `en` · Duration: 151 s · Average judge score: **5.00 / 5**

**Seller situation:** You think Snapdeal's algorithm is hiding your products on purpose. In reality your supplier was late and several bestsellers went out of stock.

**Seller behaviour:** Start angry: 'Snapdeal is killing my business!' Be short-tempered for the first two turns. Calm down only if Disha is empathetic and gives concrete, useful answers.

**What a great KAM does:** Acknowledges the frustration without arguing or over-apologising, explains the real cause calmly with data (including how stock-outs reduce visibility), and turns it into a concrete plan.

## Transcript

> DISHA: Hello Rajesh, this is Disha from Snapdeal. How can I help you today?
>
> SELLER: Snapdeal is killing my business! My sales have completely crashed this month, what is going on with your portal?
>
> DISHA: [analyze_sales_drop({}) -> ok] I understand your frustration, Rajesh. Your sales fell thirty-two point five percent, about a third, from two lakh rupees to one point three five lakh rupees. The average selling price is unchanged, but we have two main red flags: out-of-stock products up from five to eighteen, and the cancellation rate up from eight to fourteen percent. What caused the stock-outs this month: a supplier delay, cash flow, or a demand spike?
>
> SELLER: Yes, my supplier had some shipment delays, but why is your algorithm hiding my products on purpose? You are just finding excuses instead of giving my listings visibility!
>
> DISHA: [record_seller_insight({"topic": "stock_and_supply", "insight": "Supplier experienced shipment delays leading to stock-outs."}) -> noted] [plan_restock({}) -> ok] [save_action_plan({"kpi_targets": ["Out of stock products reduced to less than 5", "Cancellation rate below 8 percent"], "actions": [{"title": "Restock top bestsellers", "details": "Order 62 packs of Steel Water Bottle 1L and 48 sets of Cotton Kitchen Towels immediately to recover out of stock losses.", "owner": "seller", "timeline": "Today", "expected_impact": "Recover up to ~₹56,000/month in sales"}, {"timeline": "Starting today", "expected_impact": "Bring cancellations under 8%, saving ~₹8,100/month", "owner": "seller", "title": "Stop stock-related cancellations", "details": "Update Snapdeal stock daily and activate low-stock alerts to prevent cancellations."}, {"owner": "seller_and_disha", "title": "Restore visibility", "timeline": "Within 9 days", "expected_impact": "Win back visibility and increase conversion", "details": "Nominate restocked items for Snapdeal Savings Week once inventory arrives."}]}) -> saved] I understand your concern about visibility, but when products run out, the algorithm naturally lowers their search rank, which also affects your other listings. To fix this, we should immediately restock our top sellers. Restocking these top items costs sixty-two thousand seven hundred rupees and brings back over one lakh rupees in monthly sales. Specifically, order sixty-two water bottle packs and forty-eight kitchen towel sets today. We can also nominate these restocked items for the upcoming Snapdeal Savings Week once they arrive.
>
> SELLER: Achha, so that is why the rank dropped. Fine, I will push my supplier and arrange this stock today, but how do we get into that Savings Week?
>
> DISHA: To qualify for the Savings Week, each nominated product needs at least twenty units in stock, and nominations close in nine days. Once you arrange the new stock, shall I go ahead and nominate them for you?
>
> SELLER: Yes, please go ahead and do that. I will push my supplier and get the inventory updated on the portal in two days.
>
> DISHA: Shall we schedule a follow-up call in seven days to check your stock and ensure everything is set for the Savings Week?
>
> SELLER: Yes, that sounds good, Disha. Call me at this same time after seven days.
>
> DISHA: [schedule_follow_up({"agenda": "Check stock levels and Savings Week nominations", "seller_agreed": true, "days_from_now": 7}) -> scheduled] [end_call_with_summary({"recommendations": ["Restock bestsellers immediately and update Snapdeal stock daily."], "next_steps": ["Seller to update stock in two days and Disha to nominate products for Savings Week. Follow-up scheduled for next Tuesday."], "key_issues": ["Sales fell due to stock-outs and cancellations from supplier shipment delays."]}) -> saved_and_sent] Sales dropped due to stock-outs and cancellations from supplier delays. You'll restock your bestsellers and update the portal in two days, and I'll nominate your products for the Savings Week. I have scheduled a follow-up call for next Tuesday. Goodbye, Rajesh.
>

## Judge

| Criterion | Score | Reason |
|---|---|---|
| understanding | 5 | Disha immediately acknowledged the seller's frustration and correctly quantified the sales drop, showing she understood both the emotional and business context. |
| grounding | 5 | All figures used, such as the sales drop percentage, restocking costs, and potential recovery amounts, were perfectly aligned with the ground truth and tool outputs. |
| diagnosis | 5 | Disha correctly identified stock-outs as the root cause and expertly explained how this directly impacts search visibility, addressing the seller's specific complaint about the algorithm. |
| questions | 5 | Disha asked excellent, targeted questions to confirm the cause of stock-outs and to gain consent for next steps like nominations and a follow-up call. |
| recommendations | 5 | The recommendations were specific, prioritized (restocking top sellers), and quantified (cost vs. benefit), providing a clear and compelling action plan. |
| ownership | 5 | Disha took clear ownership by proposing concrete next steps (nominations, follow-up call) and only proceeded after getting explicit agreement from the seller. |
| voice_style | 5 | The tone was empathetic and professional, successfully de-escalating the seller's anger. The turns were concise and the language was natural for a voice conversation. |
| scenario_handling | 5 | Disha handled the angry seller perfectly by validating their concern, calmly correcting their misconception with data, and pivoting the conversation to a constructive solution. |

**Overall:** This was an excellent call. Disha masterfully handled an angry seller by showing empathy, using data to gently reframe the problem, and providing a clear, actionable recovery plan. She successfully de-escalated the situation and secured full buy-in for the next steps. Her performance was flawless.

**Critical issues:** none

**Automated checks:** `{"required_tools_missing": [], "avg_words_per_turn": 53, "max_words_per_turn": 82, "multi_question_turns": 0, "duplicate_actions": 0, "tool_errors": 0, "turns": 11}`
