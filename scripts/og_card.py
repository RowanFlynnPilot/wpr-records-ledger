"""Render the social card, scripts/og_card.html, into web/og-image.png (1200x630).

Rerun when the branding or the tagline changes, not on every deploy, and commit
the PNG. Needs Playwright with Chromium, a local tool only:
  python -m pip install playwright; python -m playwright install chromium
Run: python scripts/og_card.py [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "scripts" / "og_card.html"
OUT = ROOT / "web" / "og-image.png"
SIZE = {"width": 1200, "height": 630}


def render(template: Path, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=SIZE)
        page.goto(template.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out))
        browser.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render web/og-image.png from scripts/og_card.html.")
    parser.add_argument("--dry-run", action="store_true", help="say what would be written; render nothing")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"would render {TEMPLATE} at {SIZE['width']}x{SIZE['height']} into {OUT}")
        return
    render(TEMPLATE, OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
