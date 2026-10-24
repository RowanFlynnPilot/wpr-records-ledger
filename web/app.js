import { LEAD } from "./config.js";
import {
  benchmarkLabel, el, fmtCents, fmtDate, fmtDateTime, fmtInt, loadJSON, loadText, showError, STATUS_LABELS,
} from "./common.js";

const main = document.querySelector("main");

function fillLead(container, html, scorecard, meta) {
  container.innerHTML = html;   // a fragment from this site's own leads/, never data
  const sum = (k) => scorecard.reduce((t, a) => t + a[k], 0);
  const values = {
    requests: fmtInt(sum("requests")),
    agencies: fmtInt(scorecard.length),
    open: fmtInt(sum("open")),
    denials: fmtInt(sum("denials")),
    denials_without_reasons: fmtInt(sum("denials_without_reasons")),
    earliest: meta.earliest_filed_on ? fmtDate(meta.earliest_filed_on, { month: "long", year: "numeric" }) : "—",
  };
  for (const slot of container.querySelectorAll("[data-fill]")) slot.textContent = values[slot.dataset.fill];
}

function rate(label, value, n, nLabel, minN, bench) {
  const shown = value !== null;
  return el("div", { class: "metric" },
    el("div", { class: "metric-row" },
      el("span", { class: "metric-label" }, label),
      el("span", { class: shown ? "metric-value" : "metric-value withheld" },
        shown ? value : `Not shown: n = ${n}, below ${minN}`)),
    el("p", { class: "metric-bench" }, `${nLabel}: ${fmtInt(n)}. ${bench}`));
}

function agencyCard(a, law) {
  const minN = law.MIN_N_FOR_RATES;
  const wd = law.SIMPLE_REQUEST_BENCHMARK_WD;
  const mix = [`${fmtInt(a.simple_n)} simple`, `${fmtInt(a.complex_n)} complex`];
  if (a.unclassified_n) mix.push(`${fmtInt(a.unclassified_n)} not yet classified`);
  mix.push(`${fmtInt(a.open)} open`);
  const count = (label, n, sub = false) =>
    el("li", { class: sub ? "sub" : null }, el("span", {}, label), el("span", { class: "num" }, fmtInt(n)));
  const share = a.benchmark_met_share === null ? null : `${Math.round(a.benchmark_met_share * 100)}%`;
  return el("article", { class: "card" },
    el("div", { class: "card-head" },
      el("h3", {}, a.agency),
      el("span", { class: "card-n" }, `${fmtInt(a.requests)} request${a.requests === 1 ? "" : "s"}`)),
    el("p", { class: "card-mix" }, mix.join(" · ")),
    rate("Median working days held, simple requests", a.median_held_wd_simple, a.median_n,
         "Answered simple requests", minN,
         `DOJ guidance: about ${wd} working days is generally reasonable for a simple request.`),
    rate(`Simple requests answered within ${wd} working days`, share, a.benchmark_n,
         "Simple requests judged", minN,
         "Open requests past the mark count as missed."),
    el("ul", { class: "counts" },
      count("Denials, full or partial", a.denials),
      count("with no stated reason", a.denials_without_reasons, true),
      count("without notice of appeal rights", a.denials_missing_remedy_notice, true),
      count("“No records” responses", a.no_records),
      count("Location fees under $50", a.location_fee_under_50),
      count("Notices to an employee, s. 19.356", a.subject_notice_n),
      count("Appeals and suits filed by WPR", a.appeals)),
    el("p", { class: "metric-bench" },
      "A denial of a written request must give specific reasons and say it can be reviewed by a court " +
      "or the district attorney or attorney general, s. 19.35(4)(b). A location fee is allowed only " +
      "when that cost alone is $50 or more."));
}

function feeCell(cents, label) {
  return el("td", { class: "num", "data-label": label }, cents === null ? "—" : cents === 0 ? "Waived" : fmtCents(cents));
}

function denialNote(r) {
  if (r.status !== "denied" && r.status !== "partially_denied") return null;
  const reason = r.denial_reason === null ? "No reason stated." : `Stated reason: “${r.denial_reason}”`;
  const notice = r.remedy_notice ? "Gave notice of appeal rights." : "No notice of appeal rights.";
  return el("div", { class: "denial" }, `${reason} ${notice}`);
}

function requestRow(r) {
  const benchClass = r.benchmark_result === false ? "bench bench-missed" : "bench";
  return el("tr", {},
    el("td", { class: "date", "data-label": "Filed" }, fmtDate(r.filed_on)),
    el("td", { "data-label": "Agency" }, r.agency),
    el("td", { class: "subject" }, r.public_subject),
    el("td", { class: "status-cell", "data-label": "Status" }, el("span", { class: "status" }, STATUS_LABELS[r.status]), denialNote(r)),
    el("td", { class: "num", "data-label": "Working days held" }, fmtInt(r.held_wd)),
    el("td", { class: benchClass, "data-label": "10-day benchmark" }, benchmarkLabel(r.benchmark_result)),
    feeCell(r.fees_quoted_cents, "Fee quoted"),
    feeCell(r.fees_paid_cents, "Fee paid"));
}

function renderRequests(requests) {
  const select = document.getElementById("agency-filter");
  const body = document.getElementById("request-rows");
  const shown = document.getElementById("shown");
  for (const agency of [...new Set(requests.map((r) => r.agency))].sort()) {
    select.append(el("option", { value: agency }, agency));
  }
  const draw = () => {
    const rows = requests.filter((r) => !select.value || r.agency === select.value);
    body.replaceChildren(...(rows.length ? rows.map(requestRow)
      : [el("tr", {}, el("td", { colspan: "8", class: "empty" }, "No listed requests yet."))]));
    shown.textContent = `${fmtInt(rows.length)} of ${fmtInt(requests.length)} listed requests`;
  };
  select.addEventListener("change", draw);
  draw();
}

async function start() {
  const [scorecard, requests, meta, leadHtml] = await Promise.all([
    loadJSON("data/scorecard.json"), loadJSON("data/requests.json"), loadJSON("data/meta.json"),
    loadText(`leads/${LEAD}.html`),
  ]);
  document.getElementById("updated").textContent =
    `Updated ${fmtDateTime(meta.generated_at)} · open requests measured to ${fmtDate(meta.as_of)}`;
  for (const n of document.querySelectorAll(".min-n")) n.textContent = meta.law.MIN_N_FOR_RATES;
  fillLead(document.getElementById("lead"), leadHtml, scorecard, meta);
  document.getElementById("cards").replaceChildren(...scorecard.map((a) => agencyCard(a, meta.law)));
  renderRequests(requests);
}

start().catch((err) => showError(main, err));
