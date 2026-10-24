import { agencyCard } from "./cards.js";
import { LEAD } from "./config.js";
import {
  benchmarkLabel, el, EVENT_LABELS, fmtCents, fmtDate, fmtDateTime, fmtInt, loadJSON, loadText, plural,
  showError, STATUS_LABELS, doneLoading, warnIfStale,
} from "./common.js";

const main = document.querySelector("main");

// One round's tally, as counts: the round is small, so no shares.
function roundSummary(round, rows) {
  const n = (test) => rows.filter(test).length;
  const parts = [`${fmtInt(n((r) => r.benchmark_result === true))} answered within 10 working days`,
    `${fmtInt(n((r) => r.benchmark_result === false))} past 10`];
  const unjudged = n((r) => r.benchmark_result === null && r.status !== "open");
  const open = n((r) => r.status === "open");
  if (unjudged) parts.push(`${fmtInt(unjudged)} not judged`);
  if (open) parts.push(`${fmtInt(open)} still open`);
  return `${round}: ${fmtInt(rows.length)} custodian${rows.length === 1 ? "" : "s"}; ${parts.join(", ")}`;
}

function auditRounds(requests) {
  const rounds = {};
  for (const r of requests) if (r.audit_round) (rounds[r.audit_round] ??= []).push(r);
  for (const rows of Object.values(rounds)) rows.sort((a, b) => a.agency.localeCompare(b.agency));
  return rounds;   // keys sort newest first below
}

function fillLead(container, html, scorecard, meta, rounds) {
  container.innerHTML = html;   // a fragment from this site's own leads/, never data
  const sum = (k) => scorecard.reduce((t, a) => t + a[k], 0);
  const counts = { requests: sum("requests"), agencies: scorecard.length, open: sum("open"),
                   denials: sum("denials"), denials_without_reasons: sum("denials_without_reasons") };
  const values = {
    ...Object.fromEntries(Object.entries(counts).map(([k, n]) => [k, fmtInt(n)])),
    since: meta.earliest_filed_on
      ? ` since ${fmtDate(meta.earliest_filed_on, { month: "long", year: "numeric" })}` : "",
    audit_summary: latestRound(rounds)
      ? `Latest round, ${roundSummary(latestRound(rounds), rounds[latestRound(rounds)])}.`
      : "The first round's results will appear here once they are published.",
  };
  for (const slot of container.querySelectorAll("[data-fill]")) slot.textContent = values[slot.dataset.fill];
  for (const label of container.querySelectorAll("[data-count]")) {
    label.textContent = plural(counts[label.dataset.count], label.dataset.one, label.dataset.many);
  }
}

function feeCell(cents, label) {
  return el("td", { class: "num", "data-label": label }, cents === null ? "—" : cents === 0 ? "Waived" : fmtCents(cents));
}

// A reason pasted from a letter can run to pages: show its start, the rest on request.
const REASON_PREVIEW = 240;

function stateReason(reason) {
  if (reason === null) return "No reason stated. ";
  if (reason.length <= REASON_PREVIEW) return `Stated reason: “${reason}” `;
  const cut = reason.lastIndexOf(" ", REASON_PREVIEW);
  const start = reason.slice(0, cut > 0 ? cut : REASON_PREVIEW);
  return el("details", { class: "reason" },
    el("summary", {}, `Stated reason: “${start}…” `, el("span", { class: "reason-more" }, "Read all")),
    el("p", {}, `“${reason}”`));
}

function denialNote(r) {
  if (!["denied", "partially_denied", "denial_reversed"].includes(r.status)) return null;
  const notice = r.remedy_notice ? "Gave notice of appeal rights." : "No notice of appeal rights.";
  // s. 19.35(4)(b): an oral request is owed written reasons only on demand, and no notice.
  const oral = r.channel === "oral" ? " An oral request: neither was required." : "";
  return el("div", { class: "denial" }, stateReason(r.denial_reason), `${notice}${oral}`);
}

const latestRound = (rounds) => Object.keys(rounds).sort().reverse()[0];

function auditRow(r) {
  const benchClass = r.benchmark_result === false ? "bench bench-missed" : "bench";
  return el("tr", {},
    el("td", { class: "subject" }, r.agency),
    el("td", { class: "date", "data-label": "Filed" }, fmtDate(r.filed_on)),
    el("td", { class: "status-cell", "data-label": "Status" }, el("span", { class: "status" }, STATUS_LABELS[r.status]), denialNote(r)),
    el("td", { class: "num", "data-label": "Working days held" }, fmtInt(r.held_wd)),
    el("td", { class: benchClass, "data-label": "10-day benchmark" }, benchmarkLabel(r.benchmark_result)),
    feeCell(r.fees_quoted_cents, "Fee quoted"),
    feeCell(r.fees_paid_cents, "Fee paid"));
}

function renderAudit(rounds) {
  const names = Object.keys(rounds).sort().reverse();
  if (!names.length) return;
  document.getElementById("audit").hidden = false;
  document.getElementById("audit-link").hidden = false;
  const select = document.getElementById("round-filter");
  for (const name of names) select.append(el("option", { value: name }, name));
  const draw = () => {
    const rows = rounds[select.value];
    document.getElementById("audit-rows").replaceChildren(...rows.map(auditRow));
    document.getElementById("round-summary").textContent = roundSummary(select.value, rows);
  };
  select.addEventListener("change", draw);
  draw();
  renderTrend(rounds);
}

// Each agency across every round, oldest to newest, once there are two.
function renderTrend(rounds) {
  const names = Object.keys(rounds).sort();
  if (names.length < 2) return;
  document.getElementById("audit-trend").hidden = false;
  document.getElementById("trend-head").append(...names.map((n) => el("th", { scope: "col", class: "num" }, n)));
  const agencies = [...new Set(names.flatMap((n) => rounds[n].map((r) => r.agency)))].sort();
  const cell = (rows) => {
    if (!rows.length) return el("td", { class: "num trend-gap" }, "—");
    return el("td", { class: "num" }, rows.map((r) => {
      const label = r.status === "open" ? "open" : benchmarkLabel(r.benchmark_result).toLowerCase();
      return el("span", { class: r.benchmark_result === false ? "trend-entry bench-missed" : "trend-entry" },
        el("span", { class: "trend-days" }, `${fmtInt(r.held_wd)} ${plural(r.held_wd, "day", "days")}`), el("span", { class: "trend-note" }, label));
    }));
  };
  document.getElementById("trend-rows").replaceChildren(...agencies.map((agency) => el("tr", {},
    el("th", { scope: "row" }, agency),
    names.map((n) => cell(rounds[n].filter((r) => r.agency === agency))))));
}

function timeline(events) {
  if (!events?.length) return null;
  const item = (e) => {
    const label = e.event_type === "fee_paid" && e.amount_cents === 0 ? "Agency waived the fee" : EVENT_LABELS[e.event_type];
    const amount = e.amount_cents ? `: ${fmtCents(e.amount_cents)}` : "";
    return el("li", {}, el("span", { class: "date" }, fmtDate(e.event_on)), ` ${label}${amount}`);
  };
  return el("details", { class: "timeline" }, el("summary", {}, `Timeline, ${events.length} event${events.length === 1 ? "" : "s"}`),
    el("ol", {}, events.map(item)));
}

function requestRow(r, events) {
  const benchClass = r.benchmark_result === false ? "bench bench-missed" : "bench";
  return el("tr", {},
    el("td", { class: "date", "data-label": "Filed" }, fmtDate(r.filed_on)),
    el("td", { "data-label": "Agency" }, r.agency),
    el("td", { class: "subject" }, r.public_subject, timeline(events)),
    el("td", { class: "status-cell", "data-label": "Status" }, el("span", { class: "status" }, STATUS_LABELS[r.status]), denialNote(r)),
    el("td", { class: "num", "data-label": "Working days held" }, fmtInt(r.held_wd)),
    el("td", { class: benchClass, "data-label": "10-day benchmark" }, benchmarkLabel(r.benchmark_result)),
    feeCell(r.fees_quoted_cents, "Fee quoted"),
    feeCell(r.fees_paid_cents, "Fee paid"));
}

// Years of requests would make one very long page: show them a page at a time.
const PAGE = 25;

function renderRequests(requests, events) {
  const byRef = {};
  for (const e of events) (byRef[e.ref] ??= []).push(e);
  const select = document.getElementById("agency-filter");
  const body = document.getElementById("request-rows");
  const shown = document.getElementById("shown");
  const more = document.getElementById("more");
  for (const agency of [...new Set(requests.map((r) => r.agency))].sort()) {
    select.append(el("option", { value: agency }, agency));
  }
  let limit = PAGE;
  const draw = () => {
    const rows = requests.filter((r) => !select.value || r.agency === select.value);
    const visible = rows.slice(0, limit);
    body.replaceChildren(...(rows.length ? visible.map((r) => requestRow(r, byRef[r.ref]))
      : [el("tr", {}, el("td", { colspan: "8", class: "empty" }, "No listed requests yet."))]));
    shown.textContent = `${fmtInt(visible.length)} of ${fmtInt(rows.length)} ` +
      plural(rows.length, "listed request", "listed requests") + (select.value ? ` at ${select.value}` : "");
    const left = rows.length - visible.length;
    more.hidden = left === 0;
    more.textContent = `Show ${fmtInt(Math.min(PAGE, left))} more (${fmtInt(left)} not shown)`;
  };
  select.addEventListener("change", () => { limit = PAGE; draw(); });
  more.addEventListener("click", () => { limit += PAGE; draw(); });
  draw();
}

async function start() {
  const [scorecard, requests, events, meta, leadHtml] = await Promise.all([
    loadJSON("data/scorecard.json"), loadJSON("data/requests.json"), loadJSON("data/request_events.json"),
    loadJSON("data/meta.json"), loadText(`leads/${LEAD}.html`),
  ]);
  document.getElementById("updated").textContent =
    `Updated ${fmtDateTime(meta.generated_at)} · open requests measured to ${fmtDate(meta.as_of)}`;
  warnIfStale(meta);
  for (const n of document.querySelectorAll(".min-n")) n.textContent = meta.law.MIN_N_FOR_RATES;
  const rounds = auditRounds(requests);
  fillLead(document.getElementById("lead"), leadHtml, scorecard, meta, rounds);
  document.getElementById("cards").replaceChildren(...(scorecard.length ? scorecard.map((a) => agencyCard(a, meta.law))
    : [el("p", { class: "empty-note" }, "No agency has published figures yet. A request enters them once it is " +
          `listed, or once it is ${meta.law.STATS_ONLY_EMBARGO_DAYS} days old.`)]));
  renderAudit(rounds);
  renderRequests(requests, events);
  doneLoading();
}

start().catch((err) => showError(main, err));
