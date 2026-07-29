#!/usr/bin/env python3
"""Record a polished browser walkthrough of MateriaViva."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


VIEWPORT = {"width": 2560, "height": 1440}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "demo" / "MateriaViva_demo_2K_source.webm",
    )
    return parser.parse_args()


def pause(page: Page, milliseconds: int) -> None:
    page.wait_for_timeout(milliseconds)


def show_caption(
    page: Page,
    title: str,
    subtitle: str,
    chapter: str,
    *,
    centered: bool = False,
) -> None:
    page.evaluate(
        """
        ({ title, subtitle, chapter, centered }) => {
          document.querySelector('#materiaviva-demo-overlay')?.remove()
          const overlay = document.createElement('div')
          overlay.id = 'materiaviva-demo-overlay'
          overlay.style.cssText = centered
            ? `position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;
               pointer-events:none;background:rgba(2,14,12,.82);backdrop-filter:blur(7px);
               opacity:0;transition:opacity .45s ease;font-family:'IBM Plex Sans',sans-serif;`
            : `position:fixed;left:42px;bottom:38px;z-index:2147483647;pointer-events:none;
               opacity:0;transform:translateY(12px);transition:opacity .35s ease,transform .35s ease;
               font-family:'IBM Plex Sans',sans-serif;`

          const card = document.createElement('div')
          card.style.cssText = centered
            ? `width:min(960px,80vw);padding:60px 68px;border:1px solid rgba(91,232,183,.55);
               background:linear-gradient(135deg,rgba(4,31,27,.97),rgba(3,18,17,.97));
               box-shadow:0 30px 90px rgba(0,0,0,.45);`
            : `width:min(640px,calc(100vw - 84px));padding:24px 30px 27px;
               border-left:3px solid #5be8b7;border-top:1px solid rgba(91,232,183,.34);
               background:rgba(3,24,21,.94);box-shadow:0 18px 55px rgba(0,0,0,.38);
               backdrop-filter:blur(12px);`

          const eyebrow = document.createElement('div')
          eyebrow.textContent = chapter
          eyebrow.style.cssText = `font:600 14px/1.2 'Space Grotesk',sans-serif;letter-spacing:.18em;
                                   text-transform:uppercase;color:#ff8b45;margin-bottom:10px;`
          const heading = document.createElement(centered ? 'h1' : 'h2')
          heading.textContent = title
          heading.style.cssText = centered
            ? `margin:0;color:#edf6f2;font:650 58px/1.08 'Space Grotesk','IBM Plex Sans',sans-serif;
               letter-spacing:-.035em;`
            : `margin:0;color:#edf6f2;font:650 32px/1.15 'Space Grotesk','IBM Plex Sans',sans-serif;
               letter-spacing:-.02em;`
          const copy = document.createElement('p')
          copy.textContent = subtitle
          copy.style.cssText = centered
            ? `margin:24px 0 0;color:#a8bbb5;font:400 22px/1.6 'IBM Plex Sans',sans-serif;`
            : `margin:10px 0 0;color:#a8bbb5;font:400 18px/1.55 'IBM Plex Sans',sans-serif;`
          card.append(eyebrow, heading, copy)
          overlay.append(card)
          document.body.append(overlay)
          requestAnimationFrame(() => {
            overlay.style.opacity = '1'
            overlay.style.transform = 'translateY(0)'
          })
        }
        """,
        {"title": title, "subtitle": subtitle, "chapter": chapter, "centered": centered},
    )


def hide_caption(page: Page) -> None:
    page.evaluate(
        """
        () => {
          const overlay = document.querySelector('#materiaviva-demo-overlay')
          if (!overlay) return
          overlay.style.opacity = '0'
          overlay.style.transform = 'translateY(10px)'
          window.setTimeout(() => overlay.remove(), 450)
        }
        """
    )
    pause(page, 500)


def smooth_scroll_to(page: Page, selector: str, offset: int = 0) -> None:
    page.evaluate(
        """
        ({ selector, offset }) => {
          const target = document.querySelector(selector)
          if (!target) throw new Error(`Missing scroll target: ${selector}`)
          const top = target.getBoundingClientRect().top + window.scrollY + offset
          window.scrollTo({ top, behavior: 'smooth' })
        }
        """,
        {"selector": selector, "offset": offset},
    )
    pause(page, 1_500)


def hover_and_click(page: Page, locator) -> None:
    locator.scroll_into_view_if_needed()
    locator.hover()
    pause(page, 450)
    locator.click()


def record_demo(url: str, output: Path) -> dict[str, object]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="materiaviva-demo-video-") as temporary:
        with sync_playwright() as playwright:
            chrome = shutil.which("google-chrome")
            browser = playwright.chromium.launch(
                headless=True,
                **({"executable_path": chrome} if chrome else {}),
            )
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=temporary,
                record_video_size=VIEWPORT,
                device_scale_factor=1,
            )
            page = context.new_page()
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.goto(url, wait_until="networkidle", timeout=120_000)
            page.wait_for_selector(".periodic-table .element")
            assert page.locator(".periodic-table .element").count() == 118

            show_caption(
                page,
                "MateriaViva",
                "Every crystal dataset unified and deduplicated into 8,225,138 searchable structures.",
                "UNIFIED CRYSTAL DATABASE · DEMO",
                centered=True,
            )
            pause(page, 4_200)
            hide_caption(page)
            pause(page, 2_600)

            smooth_scroll_to(page, ".element-lab", -24)
            show_caption(
                page,
                "Enter chemical space from the periodic table",
                "All 118 elements support include, exclude and unselected states, and combine freely.",
                "01 · ELEMENT SEARCH",
            )
            pause(page, 2_800)
            hide_caption(page)

            oxygen = page.get_by_role("button", name=re.compile(r"Oxygen \(O\): neutral"))
            with page.expect_response(
                lambda response: "/api/materials?" in response.url
                and "elements=O" in response.url
                and response.status == 200,
                timeout=120_000,
            ):
                hover_and_click(page, oxygen)
            pause(page, 2_000)

            iron = page.get_by_role("button", name=re.compile(r"Iron \(Fe\): neutral"))
            with page.expect_response(
                lambda response: "/api/materials?" in response.url
                and "elements=Fe%2CO" in response.url
                and response.status == 200,
                timeout=120_000,
            ):
                hover_and_click(page, iron)
            pause(page, 900)
            iron_included = page.get_by_role("button", name=re.compile(r"Iron \(Fe\): include"))
            with page.expect_response(
                lambda response: "/api/materials?" in response.url
                and "exclude=Fe" in response.url
                and response.status == 200,
                timeout=120_000,
            ):
                hover_and_click(page, iron_included)
            show_caption(
                page,
                "Combine and exclude filters",
                "Currently including O and excluding Fe; the result count updates with every query.",
                "01 · ELEMENT SEARCH",
            )
            pause(page, 3_200)
            hide_caption(page)

            smooth_scroll_to(page, ".catalog", -30)
            show_caption(
                page,
                "Materials Project style filtering",
                "Filter by formula, data source, band gap, density, space group, crystal system and more.",
                "02 · MATERIAL FILTERS",
            )
            pause(page, 3_000)
            hide_caption(page)

            more_filters = page.locator(".mp-filters summary")
            hover_and_click(page, more_filters)
            pause(page, 2_400)
            more_filters.click()
            pause(page, 700)

            formula = page.get_by_label("Formula, chemical system or material ID")
            formula.hover()
            with page.expect_response(
                lambda response: "/api/materials?" in response.url
                and "formula=Cr4Te8O22" in response.url
                and response.status == 200,
                timeout=120_000,
            ):
                formula.fill("Cr4Te8O22")
            pause(page, 1_400)
            experimental = page.get_by_label("Experimental only")
            with page.expect_response(
                lambda response: "/api/materials?" in response.url
                and "datasets=experimental" in response.url
                and response.status == 200,
                timeout=120_000,
            ):
                experimental.check()
            pause(page, 1_500)
            show_caption(
                page,
                "Pinpoint an experimental crystal",
                "Searching Cr\u2084Te\u2088O\u2082\u2082 and restricting the query to experimental structures.",
                "03 · STRUCTURE CATALOG",
            )
            pause(page, 3_000)
            hide_caption(page)

            first_card = page.locator(".material-card__open").first
            first_card.scroll_into_view_if_needed()
            first_card.hover()
            pause(page, 900)
            first_card.click()
            dialog = page.get_by_role("dialog", name="Material detail")
            dialog.wait_for(state="visible")
            ovito_image = dialog.get_by_role("img", name=re.compile("OVITO crystal structure render"))
            ovito_image.wait_for(state="visible", timeout=180_000)
            page.wait_for_function(
                "element => element.complete && element.naturalWidth > 0",
                arg=ovito_image.element_handle(),
                timeout=180_000,
            )
            pause(page, 2_200)
            show_caption(
                page,
                "OVITO / Tachyon high-quality rendering",
                "Structure, unit cell and material properties in one workbench, with the original CIF one click away.",
                "04 · CRYSTAL WORKBENCH",
            )
            pause(page, 3_300)
            hide_caption(page)

            top_view = dialog.get_by_role("button", name="Top")
            with page.expect_response(
                lambda response: "/render?" in response.url
                and "view=top" in response.url
                and response.status == 200,
                timeout=180_000,
            ):
                hover_and_click(page, top_view)
            page.wait_for_function(
                "element => element.complete && element.naturalWidth > 0",
                arg=dialog.get_by_role("img", name=re.compile("OVITO crystal structure render")).element_handle(),
                timeout=180_000,
            )
            pause(page, 2_800)

            interactive = dialog.get_by_role("tab", name="Interactive 3D")
            hover_and_click(page, interactive)
            canvas = dialog.locator("canvas")
            canvas.wait_for(state="visible", timeout=120_000)
            pause(page, 2_000)
            show_caption(
                page,
                "Interactive 3D in the browser",
                "Rotate, zoom and inspect atoms, bonds and cell boundaries.",
                "05 · INTERACTIVE VIEW",
            )
            pause(page, 2_800)
            hide_caption(page)

            bounds = canvas.bounding_box()
            if bounds:
                start_x = bounds["x"] + bounds["width"] * 0.56
                start_y = bounds["y"] + bounds["height"] * 0.52
                page.mouse.move(start_x, start_y, steps=15)
                page.mouse.down()
                page.mouse.move(
                    start_x - bounds["width"] * 0.20,
                    start_y + bounds["height"] * 0.06,
                    steps=50,
                )
                page.mouse.move(
                    start_x - bounds["width"] * 0.08,
                    start_y - bounds["height"] * 0.14,
                    steps=38,
                )
                page.mouse.up()
                pause(page, 2_800)

            page.screenshot(path="/tmp/materiaviva-demo-interactive.png")
            page.get_by_role("button", name="Close material detail").click()
            dialog.wait_for(state="detached")
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            pause(page, 1_800)
            show_caption(
                page,
                "MateriaViva",
                "Search, compare and discover across 8.22 million unified, deduplicated crystal structures.",
                "READY FOR EXPLORATION · 127.0.0.1:8000",
                centered=True,
            )
            pause(page, 5_000)

            video = page.video
            context.close()
            if video is None:
                raise RuntimeError("Playwright video recording was not initialized")
            video.save_as(str(output))
            browser.close()

    if console_errors:
        raise RuntimeError(f"Browser console errors: {console_errors}")
    return {
        "output": str(output),
        "bytes": output.stat().st_size,
        "console_errors": console_errors,
        "viewport": VIEWPORT,
    }


def main() -> None:
    args = parse_args()
    result = record_demo(args.url.rstrip("/"), args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
