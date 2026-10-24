"""Build the site with demo, worst-case, empty and one-of-everything data, then try to break it.

Dev-only: the stress data never ships. Each set lands in site-stress/<set>/
(gitignored) built exactly like the export's site. With --check it serves them
and, at 1280, 390 and 320px, looks for console errors, a page that scrolls
sideways, text overflowing its box, tables that have to scroll at desktop width,
and axe violations, and saves full-page screenshots to site-stress/shots/.
Needs Playwright with Chromium (a local tool, like scripts/og_card.py) and, for
--check, axe-core's axe.min.js (pass --axe; `npm pack axe-core` has it).

Run: python scripts/stress_site.py --check --axe <path to axe.min.js> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import export  # noqa: E402
import law  # noqa: E402
from tests import synthetic, worst_case  # noqa: E402

OUT = ROOT / "site-stress"
PORT = 8766
PAGES = ["index.html", "methodology.html", "embed.html?agency={agency}"]
WIDTHS = [1280, 390, 320]

# Text that spills past its box, tables that scroll sideways at desktop width.
FIND_BREAKS = """(desktop) => {
  const found = [];
  for (const el of document.querySelectorAll("main *")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || el.clientWidth === 0) continue;
    if (el.closest(".table-wrap") && !el.matches(".table-wrap")) continue;
    if (el.matches(".table-wrap")) {
      if (desktop && el.scrollWidth > el.clientWidth + 1) found.push(`table scrolls at desktop: ${el.parentElement.id}`);
      continue;
    }
    if (cs.overflowX === "visible" && el.scrollWidth > el.clientWidth + 1) {
      found.push(`${el.tagName.toLowerCase()}.${el.className} overflows ${el.scrollWidth}>${el.clientWidth}: ` +
                 `${el.textContent.trim().slice(0, 50)}`);
    }
  }
  return [...new Set(found)];
}"""


def demo() -> dict:
    """The synthetic ledger the tests use, exported without a database."""
    saved = law.HOLIDAYS
    law.HOLIDAYS = synthetic.holiday_lists()
    try:
        derived = [export.derive(r, synthetic.AS_OF) for r in synthetic.as_fetched()]
        return {"scorecard": export.scorecard(derived), "requests": export.public_requests(derived),
                "request_events": export.public_events(derived),
                "meta": export.meta(derived, synthetic.AS_OF, datetime.now(timezone.utc))}
    finally:
        law.HOLIDAYS = saved


def build(name: str, data: dict) -> Path:
    site = OUT / name
    shutil.rmtree(site, ignore_errors=True)
    shutil.copytree(export.WEB, site)
    shutil.copy(ROOT / "law.py", site / "law.py")
    shutil.copy(law.HOLIDAYS_FILE, site / "holidays.toml")
    (site / "data").mkdir()
    export.write_table(site / "data", "scorecard", data["scorecard"], export.SCORECARD_FIELDS)
    export.write_table(site / "data", "requests", data["requests"], export.REQUEST_FIELDS)
    export.write_table(site / "data", "request_events", data["request_events"], export.EVENT_FIELDS)
    meta = {**data["meta"], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (site / "data" / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return site


def check(sets: dict[str, dict], axe: Path) -> int:
    from playwright.sync_api import sync_playwright

    shots = OUT / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1",
                               "--directory", str(OUT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, data in sets.items():
                agency = data["scorecard"][0]["agency"] if data["scorecard"] else "City of Wausau"
                for page_path in PAGES:
                    for width in WIDTHS:
                        page = browser.new_page(viewport={"width": width, "height": 900})
                        errors: list[str] = []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                        page.goto(f"http://127.0.0.1:{PORT}/{name}/{page_path.format(agency=agency)}",
                                  wait_until="networkidle")
                        page.wait_for_selector("main:not([data-loading])")
                        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                        breaks = page.evaluate(FIND_BREAKS, width >= 1000)
                        if page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"):
                            breaks.append("the page scrolls sideways")
                        page.add_script_tag(path=str(axe))
                        breaks += [f"axe {v}" for v in page.evaluate(
                            "axe.run(document, {runOnly: {type: 'tag', values: "
                            "['wcag2a','wcag2aa','wcag21aa','best-practice']}}).then(r => r.violations.map(v => v.id))")]
                        stem = page_path.split(".")[0]
                        page.screenshot(path=str(shots / f"{name}-{stem}-{width}.png"), full_page=True)
                        for issue in errors + breaks:
                            print(f"{name:6} {stem:12} {width:5}  {issue}")
                            problems += 1
                        page.close()
            browser.close()
    finally:
        server.terminate()
    print(f"{problems} problem(s); screenshots in {shots}")
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render the site with stress data and look for breaks.")
    parser.add_argument("--check", action="store_true", help="serve the sets and check them in Chromium")
    parser.add_argument("--axe", type=Path, help="path to axe-core's axe.min.js (needed with --check)")
    parser.add_argument("--dry-run", action="store_true", help="name the sets and pages; build nothing")
    args = parser.parse_args(argv)
    sets = {"demo": demo(), "worst": worst_case.worst(), "empty": worst_case.empty(), "one": worst_case.one()}
    if args.dry_run:
        print(f"would build {', '.join(sets)} in {OUT} and check {len(PAGES)} pages at {WIDTHS}px")
        return
    for name, data in sets.items():
        print(f"built {build(name, data)}")
    if args.check:
        if not args.axe:
            raise SystemExit("--check needs --axe <path to axe.min.js>")
        raise SystemExit(1 if check(sets, args.axe) else 0)


if __name__ == "__main__":
    main()
