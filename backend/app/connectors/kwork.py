"""Kwork connector via unofficial mobile API + web offer flow."""

from __future__ import annotations

import base64
import logging
import re
import secrets
import string
import time
from urllib.parse import unquote, urljoin

import httpx

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_kwork_project

logger = logging.getLogger(__name__)

KWORK_API = "https://api.kwork.ru"
KWORK_WEB = "https://kwork.ru"
# Public credentials of the Kwork mobile client (same as pykwork / community libs).
_MOBILE_BASIC = base64.b64encode(b"mobile_api:qFvfRl7w").decode()
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class KworkConnector(BaseConnector):
    name = "kwork"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires = 0.0
        self._seen: set[str] = set()
        self._baselined = False

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "OrderHunter/0.1",
            "Authorization": f"Basic {_MOBILE_BASIC}",
        }

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.kwork_enabled:
            return []
        if not self.settings.kwork_login or not self.settings.kwork_password:
            logger.warning("Kwork enabled but KWORK_LOGIN/PASSWORD empty")
            return []

        orders: list[NormalizedOrder] = []
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{KWORK_API}/projects",
                    headers=self._headers(),
                    params={
                        "token": token,
                        "page": 1,
                        "categories": "",
                        "query": "",
                        "uad": "orderhunter",
                        "device": "orderhunter",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success", True) and data.get("error"):
                    raise RuntimeError(f"Kwork projects error: {data.get('error')}")

                projects = self._extract_projects(data)
                for p in projects[:30]:
                    pid = p.get("id") or p.get("project_id")
                    if not pid:
                        continue
                    pid_s = str(pid)
                    if pid_s in self._seen:
                        continue
                    self._seen.add(pid_s)
                    if not self._baselined:
                        continue
                    title = str(p.get("name") or p.get("title") or "")
                    desc = str(p.get("description") or title)
                    budget = str(
                        p.get("priceLimit")
                        or p.get("budget")
                        or p.get("price")
                        or ""
                    )
                    url = f"https://kwork.ru/projects/{pid}"
                    orders.append(
                        normalize_kwork_project(int(pid), title, desc, url, budget)
                    )
                if not self._baselined:
                    self._baselined = True
                    logger.info(
                        "Kwork baseline done (%s projects marked seen)", len(self._seen)
                    )
        except Exception:
            logger.exception("Kwork poll failed")
        return orders

    async def submit_offer(
        self,
        project_id: int,
        text: str,
        price: int,
        *,
        days: int = 7,
        kwork_name: str = "",
    ) -> dict:
        """
        Exchange offer via web flow (mobile /offer is incomplete).

        Same path as official app / kesha1225/kwork:
        getWebAuthToken → login-by-token cookies → POST /api/offer/createoffer
        """
        if not self.settings.kwork_login or not self.settings.kwork_password:
            raise RuntimeError("KWORK_LOGIN / KWORK_PASSWORD не заданы")

        description = (text or "").strip()
        if len(description) < 150:
            description = (description + "\n\nГотов уточнить детали и сроки по брифу.").strip()
            if len(description) < 150:
                description = (description + " " + "Готов приступить после согласования." * 5)[
                    :400
                ]

        name = (kwork_name or "Разработка / доработка под задачу").strip()[:80]
        price = max(int(price or 1000), 500)
        days = max(int(days or 7), 1)

        token = await self._get_token()
        async with httpx.AsyncClient(
            timeout=45.0,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            # 1) one-time web login URL from mobile API
            auth = await client.post(
                f"{KWORK_API}/getWebAuthToken",
                headers=self._headers(),
                params={
                    "token": token,
                    "url_to_redirect": "/exchange",
                    "uad": "orderhunter",
                    "device": "orderhunter",
                },
            )
            auth.raise_for_status()
            auth_data = auth.json()
            payload = auth_data.get("response") or {}
            login_url = payload.get("url")
            if not login_url or "kwork.ru" not in str(login_url):
                raise RuntimeError(
                    f"Kwork getWebAuthToken failed: {auth_data.get('error') or auth_data}"
                )

            # 2) establish web cookies
            await client.get(login_url)
            await client.get(f"{KWORK_WEB}/exchange")

            referer = f"{KWORK_WEB}/new_offer?project={project_id}"
            page = await client.get(referer)
            html = page.text or ""

            csrf = (
                client.cookies.get("csrf_user_token")
                or self._extract_csrf(html)
                or client.cookies.get("XSRF-TOKEN")
            )
            if csrf and "%" in csrf:
                csrf = unquote(csrf)
            if not csrf:
                raise RuntimeError(
                    "Kwork web: нет csrf_user_token — проверьте логин/пароль и коннекты"
                )

            draft_key = self._extract_draft_key(html) or self._gen_draft_key()
            xhr = {
                "User-Agent": _UA,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": KWORK_WEB,
                "Referer": referer,
                "Accept": "application/json, text/plain, */*",
                "X-CSRF-Token": csrf,
            }
            xsrf = client.cookies.get("XSRF-TOKEN")
            if xsrf:
                xhr["X-XSRF-TOKEN"] = unquote(xsrf)

            # best-effort draft steps (ignore soft failures)
            try:
                await client.post(
                    f"{KWORK_WEB}/quick-faq/init",
                    headers={**xhr, "Content-Type": "application/json"},
                    json={"page": "new_offer"},
                )
                await client.post(
                    f"{KWORK_WEB}/wants/create_offer_draft",
                    headers=xhr,
                    data={
                        "csrftoken": csrf,
                        "projectId": str(project_id),
                        "message": "",
                        "draftKey": draft_key,
                    },
                )
                await client.post(
                    f"{KWORK_WEB}/projects/check_is_template",
                    headers={**xhr, "Content-Type": "application/json"},
                    json={"description": description, "wantid": project_id},
                )
            except Exception:
                logger.warning("Kwork draft pre-steps failed (continuing)", exc_info=True)

            # 3) create offer
            resp = await client.post(
                f"{KWORK_WEB}/api/offer/createoffer",
                headers=xhr,
                params={"wantId": project_id, "offerType": "custom"},
                data={
                    "wantId": str(project_id),
                    "offerType": "custom",
                    "description": description,
                    "kwork_duration": str(days),
                    "kwork_price": str(price),
                    "kwork_name": name,
                },
            )
            data: dict = {}
            try:
                data = resp.json()
            except Exception:
                data = {"raw": (resp.text or "")[:500]}

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Kwork HTTP {resp.status_code}: {data.get('message') or data.get('error') or data}"
                )
            if data.get("success") is False:
                msg = (
                    data.get("message")
                    or data.get("error")
                    or data.get("response")
                    or str(data)
                )
                raise RuntimeError(str(msg))

            logger.info("Kwork offer submitted for project %s", project_id)
            return data if isinstance(data, dict) else {"ok": True, "raw": data}

    async def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires - 60:
            return self._token

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KWORK_API}/signIn",
                headers=self._headers(),
                params={
                    "login": self.settings.kwork_login,
                    "password": self.settings.kwork_password,
                    "uad": "orderhunter",
                    "device": "orderhunter",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"Kwork auth failed: {data.get('error') or data}")
            token = (data.get("response") or {}).get("token") or data.get("token")
            if not token:
                raise RuntimeError(f"Kwork auth: no token in response: {data}")
            self._token = token
            self._token_expires = now + 3600
            logger.info("Kwork auth ok")
            return token

    @staticmethod
    def _extract_projects(data: dict) -> list[dict]:
        payload = data.get("response", data.get("data", data))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("projects", "wants", "list", "items"):
                val = payload.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, dict) and isinstance(val.get("data"), list):
                    return val["data"]
        return []

    @staticmethod
    def _extract_csrf(html: str) -> str | None:
        for pat in (
            r'csrf_user_token["\']?\s*[:=]\s*["\']([a-f0-9]{16,128})["\']',
            r'name=["\']csrftoken["\']\s+value=["\']([a-f0-9]{16,128})["\']',
        ):
            m = re.search(pat, html, flags=re.I)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _extract_draft_key(html: str) -> str | None:
        for pat in (
            r'draftKey["\']?\s*[:=]\s*["\']([a-z0-9]{6,64})["\']',
            r'name=["\']draftKey["\']\s+value=["\']([a-z0-9]{6,64})["\']',
        ):
            m = re.search(pat, html, flags=re.I)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _gen_draft_key(length: int = 8) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))
