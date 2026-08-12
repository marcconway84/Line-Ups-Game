#!/usr/bin/env python3
"""Render the app icons and the link-preview image into web/.

Only needed when the artwork changes - the results are committed, so a normal
build does not run this. Requires Playwright (a development dependency):

    pip install playwright && playwright install chromium
    python scripts/make_images.py

Set LINEUPS_CHROMIUM to a Chromium binary if Playwright cannot find its own.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "web"

# Board green, chalk markings, brass disc - the same palette as the game.
OG_CARD = """
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html, body { margin: 0; padding: 0; width: 1200px; height: 630px; overflow: hidden; }
  body {
    background-color: #0e2a20;
    background-image: repeating-linear-gradient(
      90deg, rgba(255,255,255,.035) 0 8.33%, transparent 8.33% 16.66%);
    color: #eaf2ec;
    font-family: "DejaVu Sans", Verdana, sans-serif;
    display: flex; align-items: center; gap: 64px; padding: 0 80px;
    box-sizing: border-box;
  }
  .copy { flex: 1; }
  .eyebrow { color: #e8b04b; font-size: 22px; font-weight: 700;
             letter-spacing: 6px; text-transform: uppercase; margin-bottom: 18px; }
  h1 { font-size: 104px; line-height: .92; margin: 0 0 24px; letter-spacing: -1px; }
  p { font-size: 28px; color: #8fa89a; margin: 0; max-width: 20ch; line-height: 1.35; }
  /* A miniature of the pitch the game is played on. */
  .pitch { width: 300px; height: 420px; position: relative; flex: none;
           border: 2px solid rgba(234,242,236,.22); }
  .pitch .half { position: absolute; left: 0; right: 0; top: 50%;
                 border-top: 2px solid rgba(234,242,236,.22); }
  .pitch .circle { position: absolute; width: 96px; height: 96px; border-radius: 50%;
                   left: 50%; top: 50%; transform: translate(-50%,-50%);
                   border: 2px solid rgba(234,242,236,.22); }
  .disc { position: absolute; width: 40px; height: 40px; border-radius: 50%;
          transform: translate(-50%,-50%); background: #e8b04b;
          border: 2px solid #f4d9a0; }
  .disc.pale { background: rgba(10,31,24,.7); border-color: rgba(234,242,236,.35); }
</style></head><body>
  <div class="copy">
    <div class="eyebrow">The football lineup quiz</div>
    <h1>Name the<br>eleven</h1>
    <p>A famous starting XI, blanked out. Can you fill it in?</p>
  </div>
  <div class="pitch">
    <div class="half"></div><div class="circle"></div>
    __DISCS__
  </div>
</body></html>
"""


def _disc_markup() -> str:
    """A 4-4-2 laid out on the mini pitch; a few filled in, the rest still blank."""
    rows = [(1, 93), (4, 74), (4, 45), (2, 20)]
    filled = {(0, 0), (2, 1), (3, 0), (1, 2)}
    out = []
    for row_index, (count, top) in enumerate(rows):
        for col in range(count):
            left = (col + 1) / (count + 1) * 100
            pale = "" if (row_index, col) in filled else " pale"
            out.append(f'<div class="disc{pale}" style="left:{left:.1f}%;top:{top}%"></div>')
    return "\n    ".join(out)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. See this file's docstring.", file=sys.stderr)
        return 1

    svg = (WEB / "icon.svg").read_text(encoding="utf-8")
    WEB.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("LINEUPS_CHROMIUM") or None)

        for size in (180, 192, 512):
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(
                "<!DOCTYPE html><html><head><style>"
                "html,body{margin:0;padding:0;overflow:hidden;background:#0e2a20}"
                f"svg{{width:{size}px;height:{size}px;display:block}}"
                "</style></head><body>" + svg + "</body></html>"
            )
            page.wait_for_timeout(120)
            page.screenshot(path=str(WEB / f"icon-{size}.png"))
            print(f"wrote web/icon-{size}.png")
            page.close()

        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(OG_CARD.replace("__DISCS__", _disc_markup()))
        page.wait_for_timeout(150)
        page.screenshot(path=str(WEB / "og-image.png"))
        print("wrote web/og-image.png")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
