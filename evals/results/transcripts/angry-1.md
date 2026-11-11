# Angry, blames Snapdeal (run 1)

Mode: `inbound` · Language: `en` · Duration: 273 s · Average judge score: **5.00 / 5**

**Seller situation:** You think Snapdeal's algorithm is hiding your products on purpose. In reality your supplier was late and several bestsellers went out of stock.

**Seller behaviour:** Start angry: 'Snapdeal is killing my business!' Be short-tempered for the first two turns. Calm down only if Disha is empathetic and gives concrete, useful answers.

**What a great KAM does:** Acknowledges the frustration without arguing or over-apologising, explains the real cause calmly with data (including how stock-outs reduce visibility), and turns it into a concrete plan.

## Transcript

> DISHA: Hello Rajesh, this is Disha calling from Snapdeal. How can I assist you today?
>
> SELLER: Snapdeal is killing my business! My sales have completely crashed this month and I know you people are intentionally hiding my products.
>
> DISHA: [analyze_sales_drop({}) -> ok] Rajesh, your sales fell by about a third this month, from two lakh rupees to one point three five lakh rupees. Your average price is unchanged, so we are seeing fewer orders, mainly due to out-of-stock products and higher cancellations. What caused the stock-outs this month: a supplier delay, cash flow, or a demand spike?
>
> SELLER: Yes, my supplier delayed the shipment this month, but why punish my whole account for that? Just because of a few stock-outs, your system has completely killed my visibility!
>
> DISHA: [record_seller_insight({"insight": "Supplier delay caused the stock-outs this month.", "topic": "stock_and_supply"}) -> noted] I understand your frustration, Rajesh, and I've noted that the supplier delay caused the stock-outs. To help prevent this going forward, how do you update stock on Snapdeal, manually or synced, and how often?
>
> SELLER: We do it manually on the seller portal, usually two or three times a week. We don't have any automatic software or syncing.
>
> DISHA: [record_seller_insight({"topic": "inventory_process", "insight": "Updates stock manually on the seller portal two or three times a week without automatic syncing."}) -> noted] Thank you, Rajesh. Were most cancellations orders you couldn't fulfill because the item wasn't actually available?
>
> SELLER: Yes, unfortunately that was the issue. The orders kept coming in before we could mark them out of stock on the portal.
>
> DISHA: [record_seller_insight({"insight": "Cancellations occurred because orders arrived for out-of-stock items before manual portal updates.", "topic": "cancellations"}) -> noted] [plan_restock({}) -> ok] [save_action_plan({"kpi_targets": ["Out-of-stock products back to fewer than 5 within 7 days", "Cancellation rate back under 8 percent"], "actions": [{"details": "Order 18 coffee mug sets, 62 water bottle packs, 48 kitchen towel sets, 41 glass jar sets, 26 spice racks, and 14 smaller units.", "expected_impact": "Recover ₹1.07 lakh per month", "title": "Restock top out-of-stock bestsellers", "timeline": "Order today, live in 3-5 days", "owner": "seller"}, {"title": "Stop stock-related cancellations", "details": "Set unavailable items to zero immediately on the portal.", "timeline": "Starting today", "owner": "seller", "expected_impact": "Save ₹8,100 per month"}, {"title": "Win back visibility", "expected_impact": "Recover ₹9,000 lost on in-stock products", "details": "Nominate restocked bestsellers for Snapdeal Savings Week.", "owner": "seller_and_disha", "timeline": "Within 9 days"}]}) -> saved] I've noted that, Rajesh. To fix this, let's look at restocking the top products: eighteen more coffee mug sets and sixty-two water bottle packs. This should cost about twenty-four thousand rupees and bring back forty-three thousand rupees a month. Also, please update unavailable items to zero immediately on the portal, and nominate restocked bestsellers for the upcoming sale.
>
> SELLER: Okay Disha, that makes sense. The fresh shipment arrived yesterday, so I will update the inventory on the portal today and nominate them for the sale.
>
> DISHA: That is great news, Rajesh. Would you like me to set up low-stock alerts for your bestsellers and send the full restock priority list to your WhatsApp for future orders?
>
> SELLER: Yes Disha, please set up the alerts and send the list on WhatsApp. That will really help us avoid this problem again.
>
> DISHA: [take_action({"action": "set_low_stock_alerts", "seller_confirmed": true, "details": "Set low-stock alerts for all bestsellers based on the new reorder points."}) -> done] [take_action({"seller_confirmed": true, "details": "Send the full restock priority list to WhatsApp for future orders.", "action": "send_restock_priority_list"}) -> done] I have activated your low-stock alerts and sent the restock priority list to your WhatsApp. Would you like me to check in with you in seven days to see how the stock levels and sales are recovering?
>
> SELLER: Yes, Disha, please call me next week to check. Thank you for your help today.
>
> DISHA: [schedule_follow_up({"agenda": "Review stock recovery and sales progress against plan", "days_from_now": 7, "seller_agreed": true}) -> scheduled] [end_call_with_summary({"next_steps": ["Seller to update inventory portal and nominate bestsellers for the sale event.", "Follow-up call scheduled in 7 days to review recovery."], "key_issues": ["Supplier delay caused stock-outs of bestsellers, leading to lost orders and increased cancellations."], "recommendations": ["Restock top out-of-stock products.", "Update inventory to zero immediately on the portal.", "Nominate restocked items for Snapdeal Savings Week."]}) -> saved_and_sent] I've scheduled our follow-up for next week. We're focusing on restocking bestsellers like coffee mugs and water bottles, keeping stock updated to prevent cancellations, and nominating items for the sale event. Thank you, Rajesh, I'll speak to you soon!
>

## Judge

| Criterion | Score | Reason |
|---|---|---|
| understanding | 5 | Disha correctly understood the business problem (sales drop) from the start and acknowledged the seller's frustration in the second turn, showing both business and emotional comprehension. |
| grounding | 5 | All figures mentioned by Disha, including the sales drop (₹2 lakh to ₹1.35 lakh) and the phased restock plan (costing ~₹24k to recover ~₹43k), were perfectly aligned with the ground truth. |
| diagnosis | 5 | Disha immediately identified stock-outs and cancellations as the primary drivers and then used targeted questions to correctly pinpoint the supplier delay and manual inventory process as the root causes. |
| questions | 5 | The questions were perfectly sequenced, one per turn, and logically drilled down from the high-level problem to the specific root causes of stock-outs and cancellations. |
| recommendations | 5 | Provided a perfect set of three prioritized actions: a manageable, quantified restocking step, a crucial process fix for inventory updates, and a proactive step to regain visibility. |
| ownership | 5 | Excellently drove the call forward by proposing specific actions (set alerts, send list) and a follow-up, and only executed them after getting explicit confirmation from the seller. |
| voice_style | 5 | The tone was professional, empathetic ('I understand your frustration'), and concise. The language was natural for a voice call, making the interaction smooth and effective. |
| scenario_handling | 5 | Expertly handled the angry seller by calmly reframing the issue with data instead of arguing, showing empathy, and quickly pivoting to a constructive, collaborative solution. |

**Overall:** Disha's performance was outstanding. It flawlessly handled an angry seller by de-escalating with data and empathy. The diagnosis was swift and accurate, the recommendations were specific and actionable, and it took clear ownership of the next steps. This was a model call for effective, data-driven account management.

**Critical issues:** none

**Automated checks:** `{"required_tools_missing": [], "avg_words_per_turn": 38, "max_words_per_turn": 58, "multi_question_turns": 0, "duplicate_actions": 0, "tool_errors": 0, "turns": 15}`
