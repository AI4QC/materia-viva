#!/usr/bin/env python3
"""Browser-level smoke test for a running MateriaViva instance."""

from __future__ import annotations

import json
import re
import shutil

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8000"


def main() -> None:
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        chrome = shutil.which("google-chrome")
        browser = playwright.chromium.launch(
            headless=True, **({"executable_path": chrome} if chrome else {})
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.emulate_media(color_scheme="dark")
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        assert page.title() == "MateriaViva"
        assert page.get_by_role("link", name="MateriaViva home").is_visible()
        assert page.get_by_role("heading", name=re.compile("Every crystal dataset in one place")).is_visible()
        assert page.get_by_text(re.compile("Unified and deduplicated across sources")).is_visible()
        body_text = page.locator("body").inner_text()
        assert "CSAgent" not in body_text
        assert "Materials Atlas" not in body_text
        assert page.locator(".periodic-table .element").count() == 118
        assert page.get_by_text("8,225,138", exact=True).is_visible()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        assert page.locator(".element__symbol").first.evaluate("element => getComputedStyle(element).fontSize") == "19px"
        assert page.locator(".element__number").first.evaluate("element => getComputedStyle(element).fontSize") == "9.5px"
        page.screenshot(path="/tmp/materiaviva-materials-home-night.png", full_page=True)

        page.get_by_role("button", name="Switch to light mode").click()
        page.locator("html[data-theme='light']").wait_for(state="attached")
        assert page.evaluate("localStorage.getItem('mv-theme')") == "light"
        page.wait_for_function(
            "getComputedStyle(document.body).backgroundColor === 'rgb(243, 244, 236)'"
        )
        assert page.locator("body").evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(243, 244, 236)"
        page.screenshot(path="/tmp/materiaviva-materials-home-day.png", full_page=True)
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert page.get_by_role("button", name="Switch to dark mode").is_visible()

        page.locator(".mp-filters summary").click()
        assert page.get_by_label("Stability").is_visible()
        assert page.get_by_label("Metallicity").is_visible()
        page.locator(".filters").screenshot(path="/tmp/materiaviva-materials-filters.png")
        page.locator(".mp-filters summary").click()

        oxygen = page.get_by_role("button", name=re.compile(r"Oxygen \(O\): neutral"))
        with page.expect_response(lambda response: "/api/materials?" in response.url and response.status == 200):
            oxygen.click()
        assert "elements=O" in page.url
        assert page.get_by_role("button", name=re.compile(r"Oxygen \(O\): include")).is_visible()

        page.locator(".material-card__open").first.click()
        dialog = page.get_by_role("dialog", name="Material detail")
        dialog.wait_for(state="visible")
        image = dialog.get_by_role("img", name=re.compile("OVITO crystal structure render"))
        image.wait_for(state="visible")
        page.wait_for_function(
            "element => element.complete && element.naturalWidth > 0",
            arg=image.element_handle(),
        )
        page.wait_for_timeout(400)
        page.screenshot(path="/tmp/materiaviva-materials-detail.png", full_page=False)

        dialog.get_by_role("tab", name="Interactive 3D").click()
        dialog.locator("canvas").wait_for(state="visible")
        page.wait_for_timeout(1_000)
        page.screenshot(path="/tmp/materiaviva-materials-interactive.png", full_page=False)
        dialog.get_by_role("button", name="Close material detail").click()
        dialog.wait_for(state="detached")
        page.get_by_role("button", name="Switch to dark mode").click()
        page.locator("html[data-theme='dark']").wait_for(state="attached")
        assert page.evaluate("localStorage.getItem('mv-theme')") == "dark"

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mobile.goto(BASE_URL)
        mobile.wait_for_load_state("networkidle")
        assert mobile.locator(".periodic-table .element").count() == 118
        assert mobile.get_by_role("button", name=re.compile("Switch to (light|dark) mode")).is_visible()
        mobile.screenshot(path="/tmp/materiaviva-materials-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    assert not console_errors, f"browser console errors: {console_errors}"
    print(json.dumps({
        "periodic_elements": 118,
        "ovito_image_loaded": True,
        "interactive_canvas_loaded": True,
        "console_errors": console_errors,
        "screenshots": [
            "/tmp/materiaviva-materials-home-night.png",
            "/tmp/materiaviva-materials-home-day.png",
            "/tmp/materiaviva-materials-filters.png",
            "/tmp/materiaviva-materials-detail.png",
            "/tmp/materiaviva-materials-interactive.png",
            "/tmp/materiaviva-materials-mobile.png",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
