"""Sandboxed browser automation subsystem using Playwright.

Provides safe, permission-gated web navigation, form interaction,
DOM content extraction, and page snapshot capture. Restricts dangerous
schemes and unreviewed loopback socket queries.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError
from pydantic import Field

from .tools import StrictModel

logger = logging.getLogger(__name__)

DISALLOWED_SCHEMES = frozenset({"file", "data", "javascript", "about", "chrome", "ws", "wss"})
DISALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1", "169.254.169.254"})


class BrowserElement(StrictModel):
    tag: str
    text: str
    selector: str
    element_type: str
    href: str | None = None


class BrowserPageSummary(StrictModel):
    url: str
    title: str
    status: int
    elements_count: int


class BrowserContent(StrictModel):
    url: str
    title: str
    text: str
    headings: list[str]
    links: list[str]


class BrowserSecurityError(ValueError):
    pass


class BrowserOperationError(RuntimeError):
    pass


def validate_target_url(url: str, allow_localhost: bool = False) -> str:
    """Validates URL schemes and prevents internal network probing."""
    if not url or not isinstance(url, str):
        raise BrowserSecurityError("URL must be a non-empty string")

    clean_url = url.strip()
    # If the URL contains an explicit scheme, check it directly
    if "://" in clean_url or clean_url.startswith(("//", "about:", "javascript:", "data:")):
        parsed = urlparse(clean_url)
    else:
        clean_url = "https://" + clean_url
        parsed = urlparse(clean_url)

    scheme = parsed.scheme.lower()
    if scheme in DISALLOWED_SCHEMES or scheme not in ("http", "https"):
        raise BrowserSecurityError(f"URL scheme '{scheme}' is prohibited")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise BrowserSecurityError("Missing hostname in target URL")

    if not allow_localhost and (hostname in DISALLOWED_HOSTS or hostname.startswith("127.") or hostname.endswith(".local")):
        raise BrowserSecurityError(f"Navigation to local host '{hostname}' is restricted")

    return clean_url


class BrowserAutomationService:
    """Manages an isolated Chromium browser instance for automated web tasks."""

    def __init__(self, headless: bool = True, default_timeout_ms: int = 15000):
        self.headless = headless
        self.default_timeout_ms = default_timeout_ms
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()

    async def _ensure_page(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page

        if not self._playwright:
            self._playwright = await async_playwright().start()

        if not self._browser or not self._browser.is_connected():
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                chromium_sandbox=True,
            )

        if not self._context:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 BEL/1.0",
                accept_downloads=False,
            )

        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)
        return self._page

    async def navigate(self, url: str, allow_localhost: bool = False) -> BrowserPageSummary:
        """Navigates to a validated URL and returns a page summary."""
        validated_url = validate_target_url(url, allow_localhost=allow_localhost)
        async with self._lock:
            page = await self._ensure_page()
            try:
                response = await page.goto(validated_url, wait_until="domcontentloaded")
                status = response.status if response else 200
                title = await page.title()

                # Count interactive elements
                elements = await page.query_selector_all("a, button, input, textarea, select")
                return BrowserPageSummary(
                    url=page.url,
                    title=title,
                    status=status,
                    elements_count=len(elements),
                )
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Navigation failed: {exc}") from exc

    async def click_element(self, selector: str) -> dict:
        """Clicks an element matching the CSS or text selector."""
        async with self._lock:
            page = await self._ensure_page()
            try:
                await page.click(selector, timeout=5000)
                await page.wait_for_load_state("domcontentloaded")
                return {
                    "ok": True,
                    "action": "click",
                    "selector": selector,
                    "url": page.url,
                    "title": await page.title(),
                }
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Click failed on '{selector}': {exc}") from exc

    async def fill_field(self, selector: str, value: str) -> dict:
        """Fills an input or textarea field."""
        async with self._lock:
            page = await self._ensure_page()
            try:
                await page.fill(selector, value, timeout=5000)
                return {
                    "ok": True,
                    "action": "fill",
                    "selector": selector,
                    "value_length": len(value),
                }
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Fill failed on '{selector}': {exc}") from exc

    async def extract_content(self, max_chars: int = 16000) -> BrowserContent:
        """Extracts text, headings, and primary hyperlinks from current page."""
        async with self._lock:
            page = await self._ensure_page()
            try:
                title = await page.title()
                raw_text = await page.inner_text("body")
                clean_text = re.sub(r"\n{3,}", "\n\n", raw_text.strip())[:max_chars]

                # Extract headings
                heading_elements = await page.query_selector_all("h1, h2, h3")
                headings = []
                for h in heading_elements[:15]:
                    txt = (await h.inner_text()).strip()
                    if txt:
                        headings.append(txt)

                # Extract top links
                link_elements = await page.query_selector_all("a[href]")
                links = []
                for a in link_elements[:25]:
                    href = await a.get_attribute("href")
                    txt = (await a.inner_text()).strip()
                    if href and not href.startswith(("#", "javascript:", "mailto:")):
                        links.append(f"{txt} ({href})" if txt else href)

                return BrowserContent(
                    url=page.url,
                    title=title,
                    text=clean_text,
                    headings=headings,
                    links=links,
                )
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Content extraction failed: {exc}") from exc

    async def get_interactive_elements(self, max_elements: int = 40) -> list[BrowserElement]:
        """Discovers buttons, links, and inputs on the active web page."""
        async with self._lock:
            page = await self._ensure_page()
            elements: list[BrowserElement] = []
            try:
                items = await page.query_selector_all("a, button, input:not([type='hidden']), textarea, select")
                for el in items[:max_elements]:
                    if not await el.is_visible():
                        continue
                    tag = (await el.evaluate("node => node.tagName")).lower()
                    text = (await el.inner_text() or await el.get_attribute("placeholder") or await el.get_attribute("value") or "").strip()
                    el_id = await el.get_attribute("id")
                    name = await el.get_attribute("name")
                    href = await el.get_attribute("href")

                    # Generate selector
                    if el_id:
                        selector = f"#{el_id}"
                    elif name:
                        selector = f"{tag}[name='{name}']"
                    elif text:
                        selector = f"{tag}:has-text('{text[:25]}')"
                    else:
                        selector = tag

                    elements.append(
                        BrowserElement(
                            tag=tag,
                            text=text[:100],
                            selector=selector,
                            element_type=tag,
                            href=href,
                        )
                    )
                return elements
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Element enumeration failed: {exc}") from exc

    async def capture_screenshot(self, format: Literal["jpeg", "png"] = "jpeg") -> bytes:
        """Captures page screenshot bytes."""
        async with self._lock:
            page = await self._ensure_page()
            try:
                screenshot_bytes = await page.screenshot(
                    type=format,
                    quality=80 if format == "jpeg" else None,
                    full_page=False,
                )
                return screenshot_bytes
            except PlaywrightError as exc:
                raise BrowserOperationError(f"Screenshot capture failed: {exc}") from exc

    async def close(self) -> None:
        """Tears down page, context, and browser process."""
        async with self._lock:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser and self._browser.is_connected():
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
