import logging
import re
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_fl_project

logger = logging.getLogger(__name__)


class FlRuConnector(BaseConnector):
    name = "fl_ru"

    def __init__(self):
        self.settings = get_settings()
        self._seen: set[str] = set()

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.fl_ru_enabled:
            return []

        orders: list[NormalizedOrder] = []
        first_run = not self._seen
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(self.settings.fl_ru_category_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                if self.settings.fl_ru_login and self.settings.fl_ru_password:
                    await self._try_login(page)

                items = await page.query_selector_all("div[id^='projectid_'], .b-post")
                if not items:
                    links = await page.query_selector_all("a[href*='/projects/']")
                    for link in links[:30]:
                        href = await link.get_attribute("href")
                        title = (await link.inner_text()).strip()
                        if not href or not title or len(title) < 10:
                            continue
                        pid = self._extract_id(href)
                        if not pid or pid in self._seen:
                            continue
                        self._seen.add(pid)
                        full_url = urljoin("https://www.fl.ru", href)
                        orders.append(
                            normalize_fl_project(pid, title, title, full_url)
                        )
                else:
                    for item in items[:25]:
                        pid = await item.get_attribute("id")
                        if pid:
                            pid = pid.replace("projectid_", "")
                        link_el = await item.query_selector("a[href*='/projects/']")
                        if not link_el:
                            continue
                        href = await link_el.get_attribute("href") or ""
                        title = (await link_el.inner_text()).strip()
                        if not pid:
                            pid = self._extract_id(href) or ""
                        if not pid or pid in self._seen:
                            continue
                        self._seen.add(pid)
                        desc_el = await item.query_selector(".b-post__txt, .text")
                        desc = title
                        if desc_el:
                            desc = (await desc_el.inner_text()).strip() or title
                        budget_el = await item.query_selector(".b-post__price, .cost")
                        budget = ""
                        if budget_el:
                            budget = (await budget_el.inner_text()).strip()
                        orders.append(
                            normalize_fl_project(
                                pid,
                                title,
                                desc,
                                urljoin("https://www.fl.ru", href),
                                budget,
                            )
                        )
                await browser.close()
                if first_run:
                    logger.info("FL.ru baseline done (%s projects marked seen)", len(self._seen))
                    return []
        except Exception:
            logger.exception("FL.ru poll failed")
        return orders

    async def _try_login(self, page) -> None:
        try:
            await page.goto("https://www.fl.ru/account/login/", wait_until="domcontentloaded")
            login_input = page.locator("input[name='username'], input[name='login'], #username")
            if await login_input.count():
                await login_input.first.fill(self.settings.fl_ru_login)
                await page.locator("input[type='password']").first.fill(
                    self.settings.fl_ru_password
                )
                await page.locator("button[type='submit'], input[type='submit']").first.click()
                await page.wait_for_timeout(3000)
        except Exception:
            logger.warning("FL.ru login skipped or failed")

    @staticmethod
    def _extract_id(href: str) -> str | None:
        m = re.search(r"/projects/(\d+)", href)
        return m.group(1) if m else None
