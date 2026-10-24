import { agencyCard } from "./cards.js";
import { LEAD } from "./config.js";
import {
  benchmarkLabel, el, EVENT_LABELS, fmtCents, fmtDate, fmtDateTime, fmtInt, loadJSON, loadText, showError,
  STATUS_LABELS, doneLoading, warnIfStale,
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
  const values = {
    requests: fmtInt(sum("requests")),
    agencies: fmtInt(scorecard.length),
    open: fmtInt(sum("open")),
    denials: fmtInt(sum("denials")),
    denials_without_reasons: fmtInt(sum("denials_without_reasons")),
    earliest: meta.earliest_filed_on ? fmtDate(meta.earliest_filed_on, { month: "long", year: "numeric" }) : "—",
    audit_summary: latestRound(rounds)
      ? `Latest round, ${roundSummary(latestRound(rounds), rounds[latestRound(rounds)])}.`
      : "The first round's results will appear here once they are published.",
  };
  for (const slot of container.querySelectorAll("[data-fill]")) slot.textContent = values[slot.dataset.fill];
}

function feeCell(cents, label) {
  return el("td", { class: "num", "data-label": label }, cents === null ? "—" : cents === 0 ? "Waived" : fmtCents(cents));
}

function denialNote(r) {
  if (!["denied", "partially_denied", "denial_reversed"].includes(r.status)) return null;
  const reason = r.denial_reason === null ? "No reason stated." : `Stated reason: “${r.denial_reason}”`;
  const notice = r.remedy_notice ? "Gave notice of appeal rights." : "No notice of appeal rights.";
  // s. 19.35(4)(b): an oral request is owed written reasons only on demand, and no notice.
  const oral = r.channel === "oral" ? " An oral request: neither was required." : "";
  return el("div", { class: "denial" }, `${reason} ${notice}${oral}`);
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

function renderRequests(requests, events) {
  const byRef = {};
  for (const e of events) (byRef[e.ref] ??= []).push(e);
  const select = document.getElementById("agency-filter");
  const body = document.getElementById("request-rows");
  const shown = document.getElementById("shown");
  for (const agency of [...new Set(requests.map((r) => r.agency))].sort()) {
    select.append(el("option", { value: agency }, agency));
  }
  const draw = () => {
    const rows = requests.filter((r) => !select.value || r.agency === select.value);
    body.replaceChildren(...(rows.length ? rows.map((r) => requestRow(r, byRef[r.ref]))
      : [el("tr", {}, el("td", { colspan: "8", class: "empty" }, "No listed requests yet."))]));
    shown.textContent = `${fmtInt(rows.length)} of ${fmtInt(requests.length)} listed requests`;
  };
  select.addEventListener("change", draw);
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
  document.getElementById("cards").replaceChildren(...scorecard.map((a) => agencyCard(a, meta.law)));
  renderAudit(rounds);
  renderRequests(requests, events);
  doneLoading();
}

start().catch((err) => showError(main, err));
