import { el, fmtDate, fmtDateTime, loadJSON, loadText, showError } from "./common.js";

const DESCRIPTIONS = {
  SIMPLE_REQUEST_BENCHMARK_WD: "Working days DOJ calls generally reasonable for a simple request",
  LOCATION_FEE_THRESHOLD_CENTS: "Location cost, in cents, below which no location fee may be charged",
  MIN_N_FOR_RATES: "Fewest requests a median or share may rest on",
  STATS_ONLY_EMBARGO_DAYS: "Days before an open, unlisted request enters the figures",
};

// One collapsible list per agency: each skips its own closures.
function renderHolidays(container, holidays) {
  const agencies = Object.keys(holidays);
  if (!agencies.length) {
    container.replaceChildren(el("p", { class: "warning" }, "No holiday list has been set."));
    return;
  }
  container.replaceChildren(...agencies.map((agency) => el("details", { class: "holiday-agency" },
    el("summary", {}, agency),
    Object.entries(holidays[agency]).flatMap(([year, days]) => [
      el("h4", {}, year),
      el("ul", { class: "holidays" },
        days.map((d) => el("li", {}, fmtDate(d, { weekday: "short", month: "short", day: "numeric", year: "numeric" })))),
    ]))));
}

async function start() {
  const [meta, source] = await Promise.all([loadJSON("data/meta.json"), loadText("law.py")]);
  const { HOLIDAYS, ...values } = meta.law;
  document.getElementById("updated").textContent = `Rules as of ${fmtDateTime(meta.generated_at)}`;
  for (const slot of document.querySelectorAll("[data-law]")) slot.textContent = values[slot.dataset.law];
  document.getElementById("values").replaceChildren(...Object.entries(values).map(([name, value]) =>
    el("tr", {}, el("td", {}, name), el("td", {}, String(value)), el("td", {}, DESCRIPTIONS[name] ?? ""))));
  renderHolidays(document.getElementById("holidays"), HOLIDAYS);
  document.getElementById("source").textContent = source;
}

start().catch((err) => showError(document.querySelector("main"), err));
