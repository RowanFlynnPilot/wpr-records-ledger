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
  denied: "Denied",
  no_records: "No records",
  withdrawn: "Withdrawn",
};

export function benchmarkLabel(result) {
  if (result === true) return "Within 10 days";
  if (result === false) return "Past 10 days";
  return "Not judged";
}

export function showError(container, err) {
  container.replaceChildren(el("p", { class: "load-error" }, `Could not load the ledger's data (${err.message}).`));
}
