import logging
import re
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_freelancehunt_project

logger = logging.getLogger(__name__)

_SKIP_SLUGS = {"add", "list"}


class FreelancehuntConnector(BaseConnector):
    """Assist-only: poll skill/projects feed, open URL + paste draft in bot."""

    name = "freelancehunt"

    def __init__(self):
        self.settings = get_settings()
        self._seen: set[str] = set()

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.freelancehunt_enabled:
            return []

        orders: list[NormalizedOrder] = []
        first_run = not self._seen
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(
                    self.settings.freelancehunt_projects_url,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

                links = await page.query_selector_all("a[href*='/project/']")
                for link in links[:50]:
                    href = await link.get_attribute("href") or ""
                    title = (await link.inner_text()).strip()
                    if not href or not title or len(title) < 10:
                        continue
                    pid = self._extract_id(href)
                    if not pid or pid in self._seen:
                        continue
                    self._seen.add(pid)
                    full_url = urljoin("https://freelancehunt.com", href)
                    # Truncate noisy card text (budget/bids prefixes)
                    clean_title = title.split("\n")[0].strip()[:500]
                    orders.append(
                        normalize_freelancehunt_project(
                            pid, clean_title, clean_title, full_url
                        )
                    )

                await browser.close()
                if first_run:
                    logger.info(
                        "Freelancehunt baseline done (%s projects marked seen)",
                        len(self._seen),
                    )
                    return []
        except Exception:
            logger.exception("Freelancehunt poll failed")
        return orders

    @staticmethod
    def _extract_id(href: str) -> str | None:
        # /project/slug/1640788.html
        m = re.search(r"/project/([^/]+)/(\d+)\.html", href)
        if m:
            slug = m.group(1).lower()
            if slug in _SKIP_SLUGS:
                return None
            return m.group(2)
        m = re.search(r"/project/(\d+)", href)
        return m.group(1) if m else None
