// Shared by both pages: data loading, formatting, the masthead's dates.

export async function loadJSON(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

export async function loadText(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.text();
}

// Every value from the data is set as text, never parsed as HTML.
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const fmtInt = (n) => n.toLocaleString("en-US");

export function fmtDate(iso, opts = { month: "short", day: "numeric", year: "numeric" }) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", opts);
}

export function fmtDateTime(iso) {
  return new Date(iso).toLocaleString("en-US", {
    month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "America/Chicago", timeZoneName: "short",
  });
}

export const fmtCents = (c) =>
  c === null ? null : (c / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const STATUS_LABELS = {
  open: "Open",
  fulfilled: "Fulfilled",
  partially_denied: "Partly denied",
  denial_reversed: "Denied, later released",
  denied: "Denied",
  no_records: "No records",
  withdrawn: "Withdrawn",
};

export const EVENT_LABELS = {
  acknowledged: "Agency acknowledged the request",
  clarification_requested: "Agency asked for clarification",
  delay_notified: "Agency said it needed more time",
  fee_quoted: "Agency quoted a fee",
  subject_notice_sent: "Agency notified the record's subject, s. 19.356",
  records_released: "Agency released a batch of records",
  fulfilled: "Agency provided the records",
  partially_denied: "Agency released some records and withheld others",
  denied: "Agency denied the request",
  no_records: "Agency said no records exist",
  denial_reversed: "Agency released everything it had withheld",
  clarification_sent: "WPR clarified the request",
  fee_paid: "WPR paid the fee",
  fee_disputed: "WPR disputed the fee",
  withdrawn: "WPR withdrew the request",
  appealed_da: "WPR asked the district attorney to review",
  appealed_ag: "WPR asked the attorney general to review",
  mandamus_filed: "WPR sued for the records (mandamus)",
};

export function benchmarkLabel(result) {
  if (result === true) return "Within 10 days";
  if (result === false) return "Past 10 days";
  return "Not judged";
}

// The export runs nightly; data older than this means it has stopped.
const STALE_AFTER_MS = 2 * 24 * 60 * 60 * 1000;

export function warnIfStale(meta, anchor = document.querySelector(".masthead")) {
  if (Date.now() - new Date(meta.generated_at).getTime() <= STALE_AFTER_MS) return null;
  const banner = el("p", { class: "stale-banner", role: "status" },
    `These figures were last rebuilt ${fmtDateTime(meta.generated_at)}. The nightly update may have stopped, ` +
    "so they may be out of date.");
  anchor.after(banner);
  return banner;
}

// Everything below the masthead stays hidden until the data has rendered, then
// appears at once: nothing the reader sees moves as the page fills in.
export function doneLoading() {
  document.querySelector("main").removeAttribute("data-loading");
}

export function showError(container, err) {
  doneLoading();
  container.replaceChildren(el("p", { class: "load-error" }, `Could not load the ledger's data (${err.message}).`));
}
