import logging
import re
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_weblancer_project

logger = logging.getLogger(__name__)


class WeblancerConnector(BaseConnector):
    """Assist-only: poll Weblancer web-programming feed."""

    name = "weblancer"

    def __init__(self):
        self.settings = get_settings()
        self._seen: set[str] = set()

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.weblancer_enabled:
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
                    self.settings.weblancer_projects_url,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2500)

                links = await page.query_selector_all("a[href*='/freelance/']")
                for link in links[:50]:
                    href = await link.get_attribute("href") or ""
                    title = (await link.inner_text()).strip()
                    if not href or not title or len(title) < 10:
                        continue
                    pid = self._extract_id(href)
                    if not pid or pid in self._seen:
                        continue
                    # skip category index pages without numeric id
                    self._seen.add(pid)
                    full_url = urljoin("https://www.weblancer.net", href)
                    clean = title.split("\n")[0].strip()[:500]
                    orders.append(
                        normalize_weblancer_project(pid, clean, clean, full_url)
                    )

                await browser.close()
                if first_run:
                    logger.info(
                        "Weblancer baseline done (%s projects marked seen)",
                        len(self._seen),
                    )
                    return []
        except Exception:
            logger.exception("Weblancer poll failed")
        return orders

    @staticmethod
    def _extract_id(href: str) -> str | None:
        # /freelance/veb-programmirovanie-31/slug-1268043/
        m = re.search(r"/freelance/[^/]+/.+-(\d+)/?(?:\?|$)", href, re.I)
        return m.group(1) if m else None
