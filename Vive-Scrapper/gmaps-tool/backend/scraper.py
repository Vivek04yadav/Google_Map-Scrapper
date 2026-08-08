"""
Core Google Maps scraping logic, refactored to report progress via
callbacks so the API layer can stream live updates to the frontend.

Scraping Google Maps is against Google's Terms of Service. This is
intended for personal / low-volume research use, not commercial resale
or high-frequency scraping. Google's DOM changes periodically, so the
CSS selectors below may need updating over time.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ProgressCallback = Callable[[dict], None]
StatusCallback = Callable[[str], None]


def scrape_google_maps(
    query: str,
    limit: int = 30,
    headless: bool = True,
    scroll_pause: float = 1.5,
    on_result: Optional[ProgressCallback] = None,
    on_status: Optional[StatusCallback] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[dict]:
    """
    Scrape up to `limit` business listings for `query` from Google Maps.

    on_result(row: dict)   -- called once per scraped listing, immediately
    on_status(message: str) -- called with human-readable phase updates
    should_stop() -> bool  -- polled periodically; return True to cancel early
    """
    results: list[dict] = []
    seen_names: set[str] = set()

    def status(msg: str):
        if on_status:
            on_status(msg)

    with sync_playwright() as p:
        status("Launching browser…")
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        status(f"Opening search: {query}")
        page.goto(search_url, timeout=60000)

        try:
            page.wait_for_selector('div[role="feed"]', timeout=15000)
        except PlaywrightTimeoutError:
            status("No results feed found — Google may have changed layout, or query resolved to a single place.")
            browser.close()
            return results

        feed = page.locator('div[role="feed"]')

        status("Scrolling to load listings…")
        prev_count = 0
        stagnant_rounds = 0
        while stagnant_rounds < 6:
            if should_stop and should_stop():
                break
            cards = page.locator("a.hfpxzc")
            count = cards.count()
            if count == prev_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            prev_count = count

            feed.evaluate("(el) => el.scrollBy(0, 1200)")
            time.sleep(scroll_pause)

            if count >= limit:
                break

        cards = page.locator("a.hfpxzc")
        total = min(cards.count(), limit)
        status(f"Found {cards.count()} listing cards — visiting {total}…")

        hrefs = []
        for i in range(total):
            href = cards.nth(i).get_attribute("href")
            if href:
                hrefs.append(href)

        for idx, href in enumerate(hrefs):
            if should_stop and should_stop():
                status("Stopped by user.")
                break
            try:
                page.goto(href, timeout=30000)
                page.wait_for_timeout(1200)

                data = {"maps_url": href}

                try:
                    data["name"] = page.locator("h1").first.inner_text(timeout=5000)
                except Exception:
                    data["name"] = ""

                if not data["name"] or data["name"] in seen_names:
                    continue
                seen_names.add(data["name"])

                try:
                    data["rating"] = page.locator('div.F7nice span[aria-hidden="true"]').first.inner_text(timeout=3000)
                except Exception:
                    data["rating"] = ""

                try:
                    review_label = page.locator('div.F7nice span[aria-label*="review"]').first.get_attribute(
                        "aria-label", timeout=3000
                    )
                    data["reviews"] = "".join(filter(str.isdigit, review_label)) if review_label else ""
                except Exception:
                    data["reviews"] = ""

                try:
                    data["category"] = page.locator("button.DkEaL").first.inner_text(timeout=3000)
                except Exception:
                    data["category"] = ""

                for label, key in [("Address", "address"), ("Phone", "phone"), ("Website", "website")]:
                    try:
                        el = page.locator(
                            f'button[data-item-id*="{label.lower()}"], a[data-item-id*="{label.lower()}"]'
                        ).first
                        val = el.get_attribute("aria-label", timeout=2000) or ""
                        data[key] = val.replace(f"{label}: ", "")
                    except Exception:
                        data[key] = ""

                results.append(data)
                status(f"Scraped {len(results)}/{total}: {data['name']}")
                if on_result:
                    on_result(data)

            except Exception as e:
                status(f"Skipped a listing (error: {e})")
                continue

        browser.close()
        status("Done.")

    return results
