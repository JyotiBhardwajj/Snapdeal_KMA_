/** Rendering helpers for the live case file. All dynamic text goes through textContent (no innerHTML). */

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("data-") || key.startsWith("aria-") || key === "role" || key === "title" || key === "datetime") {
      el.setAttribute(key, value);
    } else el[key] = value;
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2Z"/></svg>';
const CLOCK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 10.4 3.5 2.1-.8 1.3L11 13V7h2v5.4Z"/></svg>';

function icon(svg) {
  // Static, trusted SVG markup only.
  const span = document.createElement("span");
  span.innerHTML = svg;
  return span.firstChild;
}

export function formatINR(value) {
  const n = Math.round(Number(value) || 0);
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.abs(n).toLocaleString("en-IN")}`;
}

function formatMetric(value, unit) {
  if (unit === "inr") return formatINR(value);
  if (unit === "ratio") return `${Math.round(value * 1000) / 10}%`;
  return Number(value).toLocaleString("en-IN");
}

const VERDICT_LABEL = {
  primary_driver: "Primary driver",
  contributing: "Contributing",
  knock_on_effect: "Knock-on effect",
  ruled_out: "Ruled out",
};

const OWNER_LABEL = {
  seller: "Owner: Seller",
  disha: "Owner: Disha",
  snapdeal_team: "Owner: Snapdeal team",
  seller_and_disha: "Owner: Seller + Disha",
};

const TOPIC_LABEL = {
  stock_and_supply: "Stock & supply",
  inventory_process: "Inventory process",
  cancellations: "Cancellations",
  pricing_competition: "Pricing",
  listings_and_visibility: "Visibility",
  operations: "Operations",
  goals_constraints: "Constraints",
  other: "Other",
};

export function renderMetrics(tbody, rows) {
  tbody.replaceChildren(
    ...rows.map((row) => {
      let change;
      if (row.unit === "ratio") {
        const pts = Math.round((row.this_month - row.last_month) * 1000) / 10;
        change = { text: `${pts > 0 ? "+" : ""}${pts} pts`, delta: pts };
      } else {
        const pct = row.last_month ? Math.round(((row.this_month - row.last_month) / row.last_month) * 1000) / 10 : 0;
        change = { text: pct === 0 ? "No change" : `${pct > 0 ? "+" : ""}${pct}%`, delta: pct };
      }
      const worse = row.higher_is_worse ? change.delta > 0 : change.delta < 0;
      const chipClass = change.delta === 0 ? "chip chip-flat" : worse ? "chip chip-bad" : "chip chip-ok";
      return h(
        "tr",
        {},
        h("td", { text: row.metric }),
        h("td", { text: formatMetric(row.last_month, row.unit) }),
        h("td", { text: formatMetric(row.this_month, row.unit) }),
        h("td", {}, h("span", { class: chipClass, text: change.text })),
      );
    }),
  );
}

function renderBridge(bridge) {
  const max = Math.max(...bridge.map((step) => Math.abs(step.value)));
  let running = 0;
  return h(
    "div",
    { class: "bridge", role: "img", "aria-label": "Sales bridge from last month to this month" },
    bridge.map((step) => {
      const isTotal = step.kind === "total";
      let left;
      let width;
      if (isTotal) {
        left = 0;
        width = step.value / max;
        running = step.value;
      } else {
        const end = running + step.value;
        left = Math.min(running, end) / max;
        width = Math.abs(step.value) / max;
        running = end;
      }
      const bar = h("span", { class: `bridge-bar ${isTotal ? "total" : step.value === 0 ? "zero" : "loss"}` });
      bar.style.left = `${left * 100}%`;
      bar.style.width = `${Math.max(width * 100, step.value === 0 ? 0 : 1)}%`;
      const valueText = isTotal ? formatINR(step.value) : step.value === 0 ? "₹0" : formatINR(step.value);
      return h(
        "div",
        { class: "bridge-row" },
        h("span", { class: "bridge-label", text: step.label }),
        h("span", { class: "bridge-track" }, bar),
        h("span", { class: `bridge-value ${!isTotal && step.value < 0 ? "loss" : ""}`, text: valueText }),
      );
    }),
  );
}

export function renderDiagnosis(el, diagnosis) {
  if (!diagnosis) return false;
  const drivers = h(
    "ul",
    { class: "drivers" },
    diagnosis.drivers.map((d) =>
      h(
        "li",
        { class: "driver" },
        h(
          "div",
          { class: "driver-top" },
          h("span", { class: "driver-name", text: d.label }),
          h("span", { class: `verdict verdict-${d.verdict}`, text: VERDICT_LABEL[d.verdict] || d.verdict }),
          d.monthly_impact_inr ? h("span", { class: "driver-impact", text: `${formatINR(-d.monthly_impact_inr)}/mo` }) : null,
        ),
        h("p", { class: "driver-headline", text: d.headline }),
        h("details", {}, h("summary", { text: "Evidence" }), h("ul", {}, d.evidence.map((e) => h("li", { text: e })))),
      ),
    ),
  );
  const warnings = diagnosis.early_warnings?.length
    ? h(
        "ul",
        { class: "warnings", "aria-label": "Early warnings" },
        h("li", {}, h("h3", { text: "Early warnings" })),
        diagnosis.early_warnings.map((w) => h("li", { class: "warning", text: w.text })),
      )
    : null;
  el.replaceChildren(
    h("p", { class: "diag-summary", text: diagnosis.summary }),
    renderBridge(diagnosis.sales_bridge),
    drivers,
    h("p", { class: "root-cause" }, h("strong", { text: "Root cause: " }), diagnosis.root_cause),
    warnings,
  );
  return true;
}

const STATUS_LABEL = { met: "Target met", on_track: "On track", behind: "Behind", off_track: "Off track" };

export function renderProgress(el, progress) {
  if (!progress) return false;
  const table = h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "metrics" },
      h(
        "thead",
        {},
        h("tr", {}, ["Metric", "Before", "Target", "Last 7 days", "Status"].map((t) => h("th", { scope: "col", text: t }))),
      ),
      h(
        "tbody",
        {},
        progress.kpis.map((k) =>
          h(
            "tr",
            {},
            h("td", { text: k.metric }),
            h("td", { text: formatMetric(k.before, k.unit) }),
            h("td", { text: formatMetric(k.target, k.unit) }),
            h("td", { text: formatMetric(k.now, k.unit) }),
            h("td", {}, h("span", { class: `status status-${k.status}`, text: STATUS_LABEL[k.status] || k.status })),
          ),
        ),
      ),
    ),
  );
  const section = (title, items) =>
    items?.length ? h("section", {}, h("h3", { text: title }), h("ul", {}, items.map((i) => h("li", { text: i })))) : null;
  el.replaceChildren(
    h("p", { class: "diag-summary", text: progress.period }),
    table,
    h(
      "div",
      { class: "progress-lists" },
      section("Wins", progress.wins),
      section("Still open", progress.open_items),
      section("New risks", progress.new_risks),
      section("Opportunities", progress.opportunities),
    ),
  );
  return true;
}

function renderRestock(plan) {
  if (!plan?.items?.length) return null;
  const funded = plan.within_budget || plan.items;
  const rows = funded.map((i) =>
    h(
      "tr",
      {},
      h("td", { text: i.product + (i.partial ? " (part)" : "") }),
      h("td", { text: String(i.order_units) }),
      h("td", { text: formatINR(i.cost_inr) }),
      h("td", { text: formatINR(i.monthly_sales_inr) }),
      h("td", { text: i.reorder_point_units ? String(i.reorder_point_units) : "–" }),
    ),
  );
  const note = plan.within_budget
    ? `Budget ${formatINR(plan.budget_inr)}: brings back ~${formatINR(plan.monthly_sales_covered_inr)}/month. Phase 2: ${plan.deferred_to_phase_2.join(", ")}.`
    : `Total ${formatINR(plan.full_plan_cost_inr)} of stock for ~${formatINR(plan.full_plan_monthly_sales_inr)} of monthly sales.`;
  const a = plan.assumptions;
  return h(
    "div",
    { class: "restock" },
    h("h3", { text: "Restock order" }),
    h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, ["Product", "Order", "Cost", "Sales/month", "Reorder at"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", {}, rows),
      ),
    ),
    h("p", {
      class: "note",
      text: `${note} Assumes ${formatINR(a.unit_cost_inr)}/unit cost, ${a.supplier_lead_time_days}-day supplier lead time + ${a.safety_days} safety days.`,
    }),
  );
}

export function renderInsights(el, insights) {
  if (!insights?.length) return false;
  el.replaceChildren(
    h(
      "ul",
      { class: "insights" },
      insights.map((i) =>
        h("li", { class: "insight" }, h("span", { class: "topic", text: TOPIC_LABEL[i.topic] || i.topic }), h("span", { text: `“${i.insight}”` })),
      ),
    ),
  );
  return true;
}

export function renderPlan(el, plan, kpis, restockPlan) {
  if (!plan?.length && !restockPlan) return false;
  plan = plan || [];
  el.replaceChildren(
    h(
      "ol",
      { class: "plan" },
      plan.map((a) =>
        h(
          "li",
          { class: "plan-item" },
          h("p", { class: "plan-title", text: a.title }),
          a.details ? h("p", { class: "plan-details", text: a.details }) : null,
          h(
            "div",
            { class: "plan-meta" },
            a.expected_impact ? h("span", { class: "tag tag-impact", text: a.expected_impact }) : null,
            h("span", { class: "tag", text: OWNER_LABEL[a.owner] || `Owner: ${a.owner}` }),
            a.timeline ? h("span", { class: "tag", text: a.timeline }) : null,
          ),
        ),
      ),
    ),
    kpis?.length ? h("div", { class: "kpis" }, h("h3", { text: "Targets" }), h("ul", {}, kpis.map((k) => h("li", { text: k })))) : null,
    renderRestock(restockPlan),
  );
  return true;
}

export function renderActions(el, actions, followUp) {
  if (!actions?.length && !followUp) return false;
  const items = (actions || []).map((a) =>
    h(
      "li",
      { class: "action" },
      h("span", { class: `action-icon ${a.status === "done" ? "" : "pending"}` }, icon(a.status === "done" ? CHECK_SVG : CLOCK_SVG)),
      h(
        "div",
        {},
        h("p", { class: "action-title", text: a.label }),
        h("p", { class: "action-text", text: a.confirmation }),
        h("p", { class: "ref", text: `Ref ${a.reference_id} · ${a.status} · ${a.at}` }),
      ),
    ),
  );
  if (followUp) {
    items.push(
      h(
        "li",
        { class: "action" },
        h("span", { class: "action-icon pending" }, icon(CLOCK_SVG)),
        h(
          "div",
          {},
          h("p", { class: "action-title", text: "Follow-up call booked" }),
          h("p", { class: "action-text", text: `${followUp.when}: ${followUp.agenda}` }),
          h("p", { class: "ref", text: `Ref ${followUp.reference_id}` }),
        ),
      ),
    );
  }
  el.replaceChildren(h("ul", { class: "actions" }, items));
  return true;
}

export function renderSummary(el, summary) {
  if (!summary) return false;
  const section = (title, items) => h("section", {}, h("h3", { text: title }), h("ul", {}, (items || []).map((i) => h("li", { text: i }))));
  el.replaceChildren(
    h(
      "div",
      { class: "summary-grid" },
      section("Key issues", summary.key_issues),
      section("Recommendations", summary.recommendations),
      section("Next steps", summary.next_steps),
    ),
    h("p", { class: "sent", text: `Sent to the seller via ${summary.sent_via} at ${summary.at}` }),
  );
  return true;
}

export function renderActivity(listEl, countEl, activity) {
  const items = activity || [];
  countEl.textContent = items.length ? `${items.length} tool call${items.length === 1 ? "" : "s"}` : "No tool calls yet";
  listEl.replaceChildren(
    ...items.map((a) => {
      const args = Object.keys(a.args || {}).length ? JSON.stringify(a.args) : "";
      return h(
        "li",
        {},
        h("time", { text: a.at }),
        h("div", {}, h("code", { text: a.tool }), " ", a.label, a.ok ? "" : " (rejected)", args ? h("div", { class: "args", text: args }) : null),
      );
    }),
  );
}

export function summaryMarkdown(caseFile, seller) {
  const lines = [];
  const list = (items) => (items || []).forEach((i) => lines.push(`- ${i}`));
  lines.push("# Call summary · Disha, Snapdeal Virtual KAM", "");
  lines.push(`Case ${caseFile.case_id} · ${seller?.seller_name ?? ""} (${seller?.business_name ?? ""}) · ${caseFile.started_at}`, "");
  if (caseFile.summary) {
    lines.push("## Key issues");
    list(caseFile.summary.key_issues);
    lines.push("", "## Recommendations");
    list(caseFile.summary.recommendations);
    lines.push("", "## Next steps");
    list(caseFile.summary.next_steps);
    lines.push("");
  }
  if (caseFile.progress) {
    lines.push("## Progress since the last call");
    caseFile.progress.kpis.forEach((k) =>
      lines.push(`- ${k.metric}: ${formatMetric(k.before, k.unit)} → ${formatMetric(k.now, k.unit)} (target ${formatMetric(k.target, k.unit)}, ${STATUS_LABEL[k.status] || k.status})`),
    );
    lines.push("");
  }
  if (caseFile.action_plan?.length) {
    lines.push("## Action plan");
    caseFile.action_plan.forEach((a, i) =>
      lines.push(`${i + 1}. **${a.title}**: ${a.details} (Impact: ${a.expected_impact}; ${OWNER_LABEL[a.owner] || a.owner}; ${a.timeline})`),
    );
    if (caseFile.kpi_targets?.length) {
      lines.push("", "Targets:");
      list(caseFile.kpi_targets);
    }
    lines.push("");
  }
  if (caseFile.restock_plan?.items?.length) {
    lines.push("## Restock order");
    (caseFile.restock_plan.within_budget || caseFile.restock_plan.items).forEach((i) =>
      lines.push(`- ${i.product}: order ${i.order_units} units, ${formatINR(i.cost_inr)} (reorder at ${i.reorder_point_units ?? "n/a"})`),
    );
    lines.push("");
  }
  if (caseFile.actions_taken?.length || caseFile.follow_up) {
    lines.push("## Done on the seller's behalf");
    (caseFile.actions_taken || []).forEach((a) => lines.push(`- ${a.label}: ${a.confirmation} (Ref ${a.reference_id})`));
    if (caseFile.follow_up) lines.push(`- Follow-up: ${caseFile.follow_up.when}, ${caseFile.follow_up.agenda} (Ref ${caseFile.follow_up.reference_id})`);
    lines.push("");
  }
  if (caseFile.insights?.length) {
    lines.push("## What the seller shared");
    caseFile.insights.forEach((i) => lines.push(`- ${i.insight}`));
    lines.push("");
  }
  return lines.join("\n");
}
