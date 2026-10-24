// The agency card, shared by the home page and the embed.
import { el, fmtInt } from "./common.js";

function rate(label, value, n, nLabel, minN, bench) {
  const shown = value !== null;
  return el("div", { class: "metric" },
    el("div", { class: "metric-row" },
      el("span", { class: "metric-label" }, label),
      el("span", { class: shown ? "metric-value" : "metric-value withheld" },
        shown ? value : `Not shown: n = ${n}, below ${minN}`)),
    el("p", { class: "metric-bench" }, `${nLabel}: ${fmtInt(n)}. ${bench}`));
}

// `level`: the agency name's heading level on the host page (h3 under the home page's h2).
export function agencyCard(a, law, level = 3) {
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
      el(`h${level}`, { class: "card-title" }, a.agency),
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
      count("later released in full", a.denials_reversed, true),
      count("“No records” responses", a.no_records),
      count("Location fees under $50", a.location_fee_under_50),
      count("Notices to an employee, s. 19.356", a.subject_notice_n),
      count("Appeals and suits filed by WPR", a.appeals)),
    el("p", { class: "metric-bench" },
      "A denial of a written request must give specific reasons and say it can be reviewed by a court " +
      "or the district attorney or attorney general, s. 19.35(4)(b). A location fee is allowed only " +
      "when that cost alone is $50 or more."));
}
