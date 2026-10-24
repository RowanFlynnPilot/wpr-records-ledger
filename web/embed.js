import { agencyCard } from "./cards.js";
import { doneLoading, el, fmtDateTime, loadJSON, showError, warnIfStale } from "./common.js";

async function start() {
  const [scorecard, meta] = await Promise.all([loadJSON("data/scorecard.json"), loadJSON("data/meta.json")]);
  const name = new URLSearchParams(location.search).get("agency");
  const agency = scorecard.find((a) => a.agency === name);
  const slot = document.getElementById("embed-card");
  if (!agency) {
    slot.replaceChildren(el("p", { class: "empty" },
      name ? "The ledger has no published figures for that agency yet." : "Name an agency: embed.html?agency=…"));
  } else {
    slot.replaceChildren(agencyCard(agency, meta.law, 2));
    document.getElementById("embed-title").textContent = `${agency.agency}: The Records Ledger, Wausau Pilot & Review`;
  }
  document.getElementById("embed-updated").textContent = `Updated ${fmtDateTime(meta.generated_at)}`;
  warnIfStale(meta, document.querySelector(".embed-head"));
  // Fonts swapping in, or the card wrapping, change the height after the first paint.
  doneLoading();
  new ResizeObserver(postHeight).observe(document.documentElement);
}

// Lets the article page size the iframe; carries nothing but the height.
function postHeight() {
  if (window.parent === window) return;
  window.parent.postMessage({ source: "wpr-records-ledger", height: document.documentElement.scrollHeight }, "*");
}


start().catch((err) => showError(document.querySelector("main"), err));
